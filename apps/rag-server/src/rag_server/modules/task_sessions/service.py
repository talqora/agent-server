"""任务会话的持久化层(纯 CRUD,无编排逻辑)。

镜像 ConversationsService:TaskSession 之于 Run,如同 Conversation 之于 Message。
所有读写按 user_id 做归属校验——多租户隔离,会话本身必须按 user 限定。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import TaskSession
from rag_server.errors import NotFoundError


class TaskSessionsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(self, user_id: int, title: str | None) -> TaskSession:
        async with self._sf() as session:
            ts = TaskSession(user_id=user_id, title=title or "新任务会话")
            session.add(ts)
            await session.commit()
            await session.refresh(ts)
            return ts

    async def list(self, user_id: int) -> list[TaskSession]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(TaskSession)
                .where(TaskSession.user_id == user_id)
                .order_by(TaskSession.updated_at.desc())
            )
            return list(rows)

    async def get(self, user_id: int, session_id: int) -> TaskSession:
        """取会话 + 全量 run(含各 run 的事件流,selectin 预加载),含归属校验。"""
        async with self._sf() as session:
            ts = await session.scalar(select(TaskSession).where(TaskSession.id == session_id))
            if ts is None or ts.user_id != user_id:
                raise NotFoundError("任务会话不存在或无权访问")
            return ts

    async def ensure_owned(self, user_id: int, session_id: int) -> TaskSession:
        """仅校验归属并返回会话本身(不拉 runs),供提交任务时用。"""
        async with self._sf() as session:
            ts = await session.scalar(select(TaskSession).where(TaskSession.id == session_id))
            if ts is None or ts.user_id != user_id:
                raise NotFoundError("任务会话不存在或无权访问")
            return ts

    async def delete(self, user_id: int, session_id: int) -> None:
        ts = await self.ensure_owned(user_id, session_id)
        async with self._sf() as session:
            await session.execute(delete(TaskSession).where(TaskSession.id == ts.id))
            await session.commit()

    async def touch_on_submit(self, user_id: int, session_id: int, task_text: str) -> None:
        """提交任务时触碰会话:刷新 updatedAt(列表按最近活跃排序);
        标题仍是默认值时用首个任务文本回填(截断 255)。"""
        ts = await self.ensure_owned(user_id, session_id)
        values: dict[str, object] = {"updated_at": func.now()}
        if ts.title == "新任务会话":
            values["title"] = task_text[:255]
        async with self._sf() as session:
            await session.execute(
                update(TaskSession).where(TaskSession.id == ts.id).values(**values)
            )
            await session.commit()
