"""task_sessions 路由:/api/agent/sessions 下的会话 CRUD(与 Node 版一致)。

列表不带 runs;详情带 runs(整段 transcript,事件为落库行形状)。
"""

from __future__ import annotations

from typing import Any

from agent_core.run_engine import RunEventRecord, event_to_wire, isoformat_ms
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from rag_server.contracts import (
    AgentTaskSession,
    AgentTaskSessionDetail,
    CreateTaskSessionReq,
    wire,
)
from rag_server.db.models import Run, RunEvent, TaskSession
from rag_server.deps import CtxDep, CurrentUserId
from rag_server.modules.task_sessions.service import TaskSessionsService

router = APIRouter(tags=["task-sessions"])


def task_session_wire(ts: TaskSession, *, with_runs: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": ts.id,
        "title": ts.title,
        "createdAt": isoformat_ms(ts.created_at),
        "updatedAt": isoformat_ms(ts.updated_at),
    }
    if with_runs:
        data["runs"] = [_run_detail(run) for run in ts.runs]
        return wire(AgentTaskSessionDetail.from_dict(data))
    return wire(AgentTaskSession.from_dict(data))


def _run_detail(run: Run) -> dict[str, Any]:
    data: dict[str, Any] = {
        "runId": run.run_id,
        "kind": run.kind,
        "status": run.status,
        "createdAt": isoformat_ms(run.created_at),
        "events": [event_to_wire(_event_record(e)) for e in run.events],
    }
    if run.progress_msg is not None:
        data["progressMsg"] = run.progress_msg
    if run.task:
        data["task"] = run.task
    return data


def _event_record(event: RunEvent) -> RunEventRecord:
    """ORM RunEvent 行 → agent-core 的 RunEventRecord(供 event_to_wire 复用)。"""
    return RunEventRecord(
        id=event.id,
        run_id=event.run_id,
        sequence_no=event.sequence_no,
        event_type=event.event_type,
        payload=dict(event.payload or {}),
        created_at=event.created_at,
    )


def _service(ctx: CtxDep) -> TaskSessionsService:
    return TaskSessionsService(ctx.session_factory)


@router.post("/agent/sessions", status_code=201)
async def create(user_id: CurrentUserId, ctx: CtxDep, req: CreateTaskSessionReq) -> JSONResponse:
    ts = await _service(ctx).create(user_id, req.title)
    return JSONResponse(status_code=201, content=task_session_wire(ts, with_runs=False))


@router.get("/agent/sessions")
async def list_sessions(user_id: CurrentUserId, ctx: CtxDep) -> JSONResponse:
    rows = await _service(ctx).list(user_id)
    return JSONResponse(content=[task_session_wire(ts, with_runs=False) for ts in rows])


@router.get("/agent/sessions/{session_id}")
async def get_session(session_id: int, user_id: CurrentUserId, ctx: CtxDep) -> JSONResponse:
    ts = await _service(ctx).get(user_id, session_id)
    return JSONResponse(content=task_session_wire(ts, with_runs=True))


@router.delete("/agent/sessions/{session_id}", status_code=204)
async def delete_session(session_id: int, user_id: CurrentUserId, ctx: CtxDep) -> Response:
    await _service(ctx).delete(user_id, session_id)
    return Response(status_code=204)
