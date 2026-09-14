"""运行引擎:异步作业(摄取/agent)的统一生命周期 + 事件溯源 + 实时广播。

与 Node 版逐条对齐(apps/node-server/src/shared/run-engine/run-engine.service.ts):
- **emit = 先落库(sequenceNo = 当前最大 + 1)再广播**(广播失败可靠回放兜底;没落库的事件永远丢了);
- **start/complete/fail:先发事件、后落状态**(保证晚连入的 SSE 总能回放到终态事件);
- 同一 run 的事件由单个 worker 串行发出;(run_id, sequence_no) 唯一约束兜底防重号;
- 存储走 ``RunRepository`` 端口(各服务用自己的 ORM 模型实现);本模块不 import 任何 ORM。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from agent_core.events import EventBus

logger = logging.getLogger("agent_core.run_engine")

RUN_STATUS_QUEUED = "queued"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"

TERMINAL_EVENT_TYPES = frozenset({"run_completed", "run_failed"})


@dataclass(frozen=True)
class RunRecord:
    """引擎视角的 run(与 ORM 解耦的只读视图)。"""

    run_id: str
    user_id: int
    kind: str
    task: str
    status: str
    ref_id: str | None
    task_session_id: int | None
    progress_msg: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True)
class RunEventRecord:
    """引擎视角的运行事件行。"""

    id: int
    run_id: str
    sequence_no: int
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class RunRepository(Protocol):
    """持久化端口(服务侧适配器实现)。"""

    async def create(
        self,
        *,
        run_id: str,
        user_id: int,
        kind: str,
        task: str,
        ref_id: str | None,
        task_session_id: int | None,
    ) -> RunRecord: ...

    async def get(self, run_id: str) -> RunRecord | None: ...

    async def update_status(
        self,
        run_id: str,
        *,
        status: str,
        progress_msg: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None: ...

    async def last_sequence_no(self, run_id: str) -> int: ...

    async def append_event(
        self,
        *,
        run_id: str,
        sequence_no: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> RunEventRecord: ...

    async def events_since(self, run_id: str, since_sequence_no: int) -> list[RunEventRecord]: ...

    async def events_all(self, run_id: str) -> list[RunEventRecord]: ...


def isoformat_ms(dt: datetime) -> str:
    """ISO8601(毫秒 + Z),与 Node Date.toJSON() 输出一致。"""
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def event_to_wire(event: RunEventRecord) -> dict[str, Any]:
    """事件行 → 线格式(与 Node 落库行 JSON 一致,camelCase)。

    SSE 的 data 与 GET /agent/sessions/:id 的 runs[].events 都是本形状。
    """
    return {
        "id": event.id,
        "runId": event.run_id,
        "sequenceNo": event.sequence_no,
        "eventType": event.event_type,
        "payload": event.payload,
        "createdAt": isoformat_ms(event.created_at),
    }


class RunEngine:
    def __init__(self, repo: RunRepository, bus: EventBus) -> None:
        self._repo = repo
        self._bus = bus

    async def create_run(
        self,
        *,
        user_id: int,
        kind: str,
        task: str,
        ref_id: str | None = None,
        task_session_id: int | None = None,
    ) -> RunRecord:
        return await self._repo.create(
            run_id=f"run-{uuid4()}",
            user_id=user_id,
            kind=kind,
            task=task,
            ref_id=ref_id,
            task_session_id=task_session_id,
        )

    async def start(self, run_id: str, progress_msg: str | None = None) -> None:
        """开始:先发 run_started 事件,再落 running 状态(与 fail 对称)。"""
        await self.emit(run_id, "run_started", {})
        await self._repo.update_status(
            run_id,
            status=RUN_STATUS_RUNNING,
            progress_msg=progress_msg,
            started_at=datetime.now(UTC),
        )

    async def complete(self, run_id: str, progress_msg: str | None = None) -> None:
        """完成:先发 run_completed 事件,再落 completed 状态。

        顺序关键——若先落终态再发事件,晚连入的 SSE 可能读到 completed 却还没看到
        run_completed 而提前收尾,漏掉终态事件。
        """
        await self.emit(
            run_id, "run_completed", {"progressMsg": progress_msg} if progress_msg else {}
        )
        await self._repo.update_status(
            run_id,
            status=RUN_STATUS_COMPLETED,
            progress_msg=progress_msg,
            completed_at=datetime.now(UTC),
        )

    async def fail(self, run_id: str, error_msg: str) -> None:
        """失败:先发 run_failed 事件(让前端拿到原因),再落 failed 状态。"""
        await self.emit(run_id, "run_failed", {"error": error_msg})
        await self._repo.update_status(
            run_id,
            status=RUN_STATUS_FAILED,
            progress_msg=error_msg[:255],
            completed_at=datetime.now(UTC),
        )

    async def emit(self, run_id: str, event_type: str, payload: dict[str, Any]) -> RunEventRecord:
        """追加事件:落库(seq = max + 1)→ 广播(Redis)。"""
        sequence_no = await self._repo.last_sequence_no(run_id) + 1
        event = await self._repo.append_event(
            run_id=run_id,
            sequence_no=sequence_no,
            event_type=event_type,
            payload=payload,
        )
        await self._bus.publish_run_event(run_id, event_to_wire(event))
        return event

    async def get_run(self, run_id: str) -> RunRecord | None:
        return await self._repo.get(run_id)

    async def get_snapshot(self, run_id: str) -> tuple[RunRecord, list[RunEventRecord]] | None:
        run = await self._repo.get(run_id)
        if run is None:
            return None
        return run, await self._repo.events_all(run_id)

    async def get_events_since(self, run_id: str, since_sequence_no: int) -> list[RunEventRecord]:
        return await self._repo.events_since(run_id, since_sequence_no)
