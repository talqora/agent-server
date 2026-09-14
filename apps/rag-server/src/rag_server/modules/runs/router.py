"""runs 路由:demo 提交 / SSE 事件流(断线补发)/ 快照。

与 Node 版逐条对齐(apps/node-server/src/modules/runs/runs.controller.ts):
- POST /api/runs/demo      造一个演示作业入队,立即返回 runId(202);
- GET  /api/runs/:id/stream SSE:支持 Last-Event-ID(或 ?lastEventId=)断线补发,
  **先订阅、后补发**,补发期间到达的实时事件由 Redis 连接缓冲,随后按 watermark 去重,
  保证"补缺 → 实时"无缝且不重号;终态事件收到即收尾;
- GET  /api/runs/:id        快照(状态 + 全量事件)。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from agent_core.queue import RUN_JOB_KIND_DEMO, RunJob
from agent_core.run_engine import (
    TERMINAL_EVENT_TYPES,
    RunEventRecord,
    event_to_wire,
    isoformat_ms,
)
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from rag_server.contracts import AgentRun, RunEventRow, RunIdResp, RunSnapshotResp, wire
from rag_server.deps import CtxDep, CurrentUserId, ProducerDep
from rag_server.errors import NotFoundError

router = APIRouter(tags=["runs"])


@router.post("/runs/demo", status_code=202)
async def demo(user_id: CurrentUserId, ctx: CtxDep, producer: ProducerDep) -> JSONResponse:
    """入队一个演示作业,返回 runId 供前端订阅进度。"""
    run = await ctx.run_engine.create_run(user_id=user_id, kind="agent_task", task="demo job")
    await producer.send(RunJob(run_id=run.run_id, user_id=user_id, kind=RUN_JOB_KIND_DEMO))
    return JSONResponse(content=wire(RunIdResp(run_id=run.run_id)))


def _parse_since_seq(request: Request) -> int:
    """断线重连的起点:优先 Last-Event-ID 头,其次 ?lastEventId= 查询参数。"""
    header = request.headers.get("last-event-id")
    query = request.query_params.get("lastEventId")
    raw = header if header is not None else query
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _frame_from_record(ev: RunEventRecord) -> dict[str, Any]:
    return {
        "id": str(ev.sequence_no),
        "event": ev.event_type,
        "data": json.dumps(event_to_wire(ev), ensure_ascii=False),
    }


def _frame_from_wire(ev: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(ev.get("sequenceNo", 0)),
        "event": str(ev.get("eventType", "message")),
        "data": json.dumps(ev, ensure_ascii=False),
    }


@router.get("/runs/{run_id}/stream")
async def stream(
    run_id: str,
    request: Request,
    user_id: CurrentUserId,
    ctx: CtxDep,
) -> EventSourceResponse:
    """订阅某个 run 的实时事件流(SSE,支持 Last-Event-ID 断线回放)。"""
    run = await ctx.run_engine.get_run(run_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("运行不存在或无权访问")
    since_seq = _parse_since_seq(request)
    terminal = run.status in ("completed", "failed")

    async def event_stream() -> AsyncIterator[dict[str, Any]]:
        # 先订阅:此刻起到达的实时事件进入 Redis 连接缓冲(不会被丢)
        subscription = await ctx.event_bus.subscribe_run(run_id)
        watermark = since_seq
        try:
            # 再补发断线期间缺失的事件(与缓冲中的实时事件按 watermark 去重)
            missed = await ctx.run_engine.get_events_since(run_id, since_seq)
            for ev in missed:
                watermark = ev.sequence_no
                yield _frame_from_record(ev)
                if ev.event_type in TERMINAL_EVENT_TYPES:
                    return
            # 接入时 run 已是终态且事件已补齐:不会再有新消息,主动收尾
            if terminal:
                return
            # 转入实时:读取缓冲 + 持续推送
            async for wire_ev in subscription.events():
                seq = int(wire_ev.get("sequenceNo", 0))
                if seq <= watermark:
                    continue
                watermark = seq
                yield _frame_from_wire(wire_ev)
                if wire_ev.get("eventType") in TERMINAL_EVENT_TYPES:
                    return
        finally:
            await subscription.close()

    return EventSourceResponse(
        event_stream(),
        ping=15,
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.get("/runs/{run_id}")
async def snapshot(run_id: str, user_id: CurrentUserId, ctx: CtxDep) -> JSONResponse:
    """运行快照:状态 + 全量事件(落库行形状)。"""
    snap = await ctx.run_engine.get_snapshot(run_id)
    if snap is None or snap[0].user_id != user_id:
        raise NotFoundError("运行不存在或无权访问")
    run, events = snap
    payload = RunSnapshotResp(
        run=AgentRun(
            run_id=run.run_id,
            kind=run.kind,
            status=run.status,
            progress_msg=run.progress_msg,
            created_at=isoformat_ms(run.created_at),
            task=run.task,
        ),
        events=[RunEventRow.from_dict(event_to_wire(e)) for e in events],
    )
    return JSONResponse(content=wire(payload))
