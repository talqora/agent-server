"""agent 任务入口(HTTP 进程):只负责建 run + 入队,真正的工具编排在 worker 跑。

进度经 SSE GET /api/runs/:runId/stream 订阅(与摄取/demo 共用同一套 run 事件流)。
"""

from __future__ import annotations

from agent_core.queue import RUN_JOB_KIND_AGENT, RunJob
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rag_server.contracts import AgentTaskResp, CreateTaskReq, wire
from rag_server.deps import CtxDep, CurrentUserId, ProducerDep
from rag_server.errors import BadRequestError
from rag_server.modules.task_sessions.service import TaskSessionsService

router = APIRouter(tags=["agent"])

TASK_MAX_CHARS = 2000


@router.post("/agent/tasks", status_code=202)
async def create_task(
    user_id: CurrentUserId,
    ctx: CtxDep,
    producer: ProducerDep,
    req: CreateTaskReq,
) -> JSONResponse:
    """提交 agent 任务,返回 runId(经 /runs/:runId/stream 订阅进度)。"""
    task = (req.task or "").strip()
    if not task:
        raise BadRequestError("task 不能为空")
    if len(task) > TASK_MAX_CHARS:
        raise BadRequestError(f"task 过长(上限 {TASK_MAX_CHARS} 字符)")

    # 先校验会话归属:非本人会话直接 404,不建 run、不入队
    sessions = TaskSessionsService(ctx.session_factory)
    session = await sessions.ensure_owned(user_id, req.session_id)

    run = await ctx.run_engine.create_run(
        user_id=user_id,
        kind="agent_task",
        task=task[:255],
        task_session_id=session.id,
    )
    await producer.send(RunJob(run_id=run.run_id, user_id=user_id, kind=RUN_JOB_KIND_AGENT))
    # 触碰会话:刷新排序时间 + 首个任务回填标题
    await sessions.touch_on_submit(user_id, session.id, task)
    return JSONResponse(status_code=202, content=wire(AgentTaskResp(run_id=run.run_id)))
