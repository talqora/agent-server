"""运行引擎单测(内存仓储 + 假广播):生命周期、事件顺序、广播形状。"""

from datetime import UTC, datetime
from typing import Any

from agent_core.run_engine import (
    RunEngine,
    RunEventRecord,
    RunRecord,
    event_to_wire,
    isoformat_ms,
)


class FakeRepo:
    """内存版 RunRepository(验证引擎逻辑,不依赖数据库)。"""

    def __init__(self) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.events: dict[str, list[RunEventRecord]] = {}
        self._event_id = 0

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
        record = RunRecord(
            run_id=run_id,
            user_id=user_id,
            kind=kind,
            task=task,
            status="queued",
            ref_id=ref_id,
            task_session_id=task_session_id,
            progress_msg=None,
            created_at=datetime.now(UTC),
            started_at=None,
            completed_at=None,
        )
        self.runs[run_id] = record
        self.events[run_id] = []
        return record

    async def get(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    async def update_status(
        self,
        run_id: str,
        *,
        status: str,
        progress_msg: str | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        old = self.runs[run_id]
        self.runs[run_id] = RunRecord(
            **{
                **old.__dict__,
                "status": status,
                "progress_msg": progress_msg if progress_msg is not None else old.progress_msg,
                "started_at": started_at if started_at is not None else old.started_at,
                "completed_at": completed_at if completed_at is not None else old.completed_at,
            }
        )

    async def last_sequence_no(self, run_id: str) -> int:
        return max((e.sequence_no for e in self.events[run_id]), default=0)

    async def append_event(
        self,
        *,
        run_id: str,
        sequence_no: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> RunEventRecord:
        self._event_id += 1
        record = RunEventRecord(
            id=self._event_id,
            run_id=run_id,
            sequence_no=sequence_no,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        self.events[run_id].append(record)
        return record

    async def events_since(self, run_id: str, since_sequence_no: int) -> list[RunEventRecord]:
        return [e for e in self.events[run_id] if e.sequence_no > since_sequence_no]

    async def events_all(self, run_id: str) -> list[RunEventRecord]:
        return list(self.events[run_id])


class FakeBus:
    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    async def publish_run_event(self, run_id: str, payload: dict[str, Any]) -> None:
        self.published.append(payload)


async def test_lifecycle_events_and_broadcast() -> None:
    repo, bus = FakeRepo(), FakeBus()
    engine = RunEngine(repo, bus)  # type: ignore[arg-type]

    run = await engine.create_run(user_id=1, kind="agent_task", task="t")
    assert run.status == "queued" and run.run_id.startswith("run-")

    await engine.start(run.run_id)
    await engine.emit(run.run_id, "step", {"step": "parsing"})
    await engine.complete(run.run_id, "done")

    snapshot = await engine.get_snapshot(run.run_id)
    assert snapshot is not None
    run_row, events = snapshot
    assert run_row.status == "completed"
    assert [e.sequence_no for e in events] == [1, 2, 3]
    assert [e.event_type for e in events] == ["run_started", "step", "run_completed"]

    # 广播顺序与形状(先落库后广播;payload 为线格式)
    assert [p["eventType"] for p in bus.published] == [
        "run_started",
        "step",
        "run_completed",
    ]
    assert bus.published[0]["runId"] == run.run_id
    assert bus.published[0]["payload"] == {}


async def test_fail_emits_error_before_status() -> None:
    repo, bus = FakeRepo(), FakeBus()
    engine = RunEngine(repo, bus)  # type: ignore[arg-type]
    run = await engine.create_run(user_id=1, kind="ingestion", task="t")
    await engine.fail(run.run_id, "boom")

    events = await engine.get_events_since(run.run_id, 0)
    assert events[-1].event_type == "run_failed"
    assert events[-1].payload == {"error": "boom"}
    row = await engine.get_run(run.run_id)
    assert row is not None and row.status == "failed" and row.progress_msg == "boom"
    assert bus.published[-1]["eventType"] == "run_failed"


async def test_get_events_since_watermark() -> None:
    repo, bus = FakeRepo(), FakeBus()
    engine = RunEngine(repo, bus)  # type: ignore[arg-type]
    run = await engine.create_run(user_id=1, kind="agent_task", task="t")
    await engine.start(run.run_id)
    await engine.emit(run.run_id, "step", {"i": 2})
    await engine.emit(run.run_id, "step", {"i": 3})
    # start=seq1, 两次 emit=seq2/3;水位线 2 → 只补 3
    missed = await engine.get_events_since(run.run_id, 2)
    assert [e.sequence_no for e in missed] == [3]


def test_event_wire_shape_and_isoformat() -> None:
    dt = datetime(2026, 9, 14, 6, 0, 0, 123000, tzinfo=UTC)
    assert isoformat_ms(dt) == "2026-09-14T06:00:00.123Z"
    record = RunEventRecord(
        id=1,
        run_id="run-1",
        sequence_no=2,
        event_type="step",
        payload={"step": "parsing"},
        created_at=dt,
    )
    assert event_to_wire(record) == {
        "id": 1,
        "runId": "run-1",
        "sequenceNo": 2,
        "eventType": "step",
        "payload": {"step": "parsing"},
        "createdAt": "2026-09-14T06:00:00.123Z",
    }
