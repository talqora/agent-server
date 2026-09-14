"""持久化适配器:把 agent-core 的端口(UserStore / RunRepository)落到 rag schema。

端口定义见 agent-core(federated.UserStore / run_engine.RunRepository);
每方法一个短事务(不跨 await 持锁)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.run_engine import RunEventRecord, RunRecord
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import Run, RunEvent, User


def _run_record(row: Run) -> RunRecord:
    return RunRecord(
        run_id=row.run_id,
        user_id=row.user_id,
        kind=row.kind,
        task=row.task,
        status=row.status,
        ref_id=row.ref_id,
        task_session_id=row.task_session_id,
        progress_msg=row.progress_msg,
        created_at=row.created_at,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def _event_record(row: RunEvent) -> RunEventRecord:
    return RunEventRecord(
        id=row.id,
        run_id=row.run_id,
        sequence_no=row.sequence_no,
        event_type=row.event_type,
        payload=dict(row.payload or {}),
        created_at=row.created_at,
    )


class SqlAlchemyUserStore:
    """UserStore 端口实现(联邦身份零接触建号用)。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def find_by_issuer_subject(self, issuer: str, subject: str) -> int | None:
        async with self._sf() as session:
            value = await session.scalar(
                select(User.id).where(User.issuer == issuer, User.subject == subject)
            )
            return int(value) if value is not None else None

    async def create_federated_user(
        self,
        *,
        issuer: str,
        subject: str,
        username: str,
        display_name: str,
        role_code: str,
    ) -> int:
        async with self._sf() as session:
            user = User(
                username=username,
                # 联合用户从不走本地密码登录:空哈希作"无本地密码"哨兵
                password_hash="",
                display_name=display_name,
                role_code=role_code,
                issuer=issuer,
                subject=subject,
            )
            session.add(user)
            await session.commit()
            return user.id


class SqlAlchemyRunRepository:
    """RunRepository 端口实现。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(
        self,
        *,
        run_id: str,
        user_id: int,
        kind: str,
        task: str,
        ref_id: str | None,
        task_session_id: int | None,
    ) -> RunRecord:
        async with self._sf() as session:
            run = Run(
                run_id=run_id,
                user_id=user_id,
                kind=kind,
                task=task,
                ref_id=ref_id,
                task_session_id=task_session_id,
                status="queued",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            return _run_record(run)

    async def get(self, run_id: str) -> RunRecord | None:
        async with self._sf() as session:
            row = await session.scalar(select(Run).where(Run.run_id == run_id))
            return _run_record(row) if row is not None else None

    async def update_status(
        self,
        run_id: str,
        *,
        status: str,
        progress_msg: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        values: dict[str, Any] = {"status": status}
        # None = 不改动(对齐 Node:undefined 字段 Prisma 不更新)
        if progress_msg is not None:
            values["progress_msg"] = progress_msg
        if started_at is not None:
            values["started_at"] = started_at
        if completed_at is not None:
            values["completed_at"] = completed_at
        async with self._sf() as session:
            await session.execute(update(Run).where(Run.run_id == run_id).values(**values))
            await session.commit()

    async def last_sequence_no(self, run_id: str) -> int:
        async with self._sf() as session:
            value = await session.scalar(
                select(func.max(RunEvent.sequence_no)).where(RunEvent.run_id == run_id)
            )
            return int(value or 0)

    async def append_event(
        self,
        *,
        run_id: str,
        sequence_no: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> RunEventRecord:
        async with self._sf() as session:
            event = RunEvent(
                run_id=run_id,
                sequence_no=sequence_no,
                event_type=event_type,
                payload=payload,
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            return _event_record(event)

    async def events_since(self, run_id: str, since_sequence_no: int) -> list[RunEventRecord]:
        async with self._sf() as session:
            rows = (
                await session.scalars(
                    select(RunEvent)
                    .where(
                        RunEvent.run_id == run_id,
                        RunEvent.sequence_no > since_sequence_no,
                    )
                    .order_by(RunEvent.sequence_no)
                )
            ).all()
            return [_event_record(r) for r in rows]

    async def events_all(self, run_id: str) -> list[RunEventRecord]:
        return await self.events_since(run_id, 0)
