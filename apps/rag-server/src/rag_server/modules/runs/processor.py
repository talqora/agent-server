"""runs 队列消费者(仅 worker 进程加载)。

统一包住 start → … → complete/fail 生命周期,按 job.kind 分派(对齐 Node 的 job.name:
ingestion / agent / demo——demo 与真实 agent 任务的 run.kind 都是 agent_task,只能靠入队 kind 区分);
每一步都经 RunEngine.emit 落库 + 广播,持有 SSE 连接的 HTTP 副本据此实时推送。
"""

from __future__ import annotations

import asyncio
import logging

from agent_core.queue import (
    RUN_JOB_KIND_AGENT,
    RUN_JOB_KIND_INGESTION,
    RunJob,
)

from rag_server.context import CoreContext
from rag_server.modules.agent.runner import AgentRunnerService
from rag_server.modules.documents.ingestion import IngestionService

DEMO_STEPS = ("parsing", "chunking", "embedding", "indexing")


class RunProcessor:
    def __init__(self, ctx: CoreContext) -> None:
        self._ctx = ctx
        self._logger = logging.getLogger("rag_server.processor")
        self._ingestion = IngestionService(
            session_factory=ctx.session_factory,
            llm=ctx.llm,
            vector=ctx.vector,
            run_engine=ctx.run_engine,
            settings=ctx.settings,
        )
        self._agent = AgentRunnerService(
            session_factory=ctx.session_factory,
            llm=ctx.llm,
            vector=ctx.vector,
            run_engine=ctx.run_engine,
            settings=ctx.settings,
        )

    async def process(self, job: RunJob) -> None:
        run = await self._ctx.run_engine.get_run(job.run_id)
        if run is None:
            raise RuntimeError(f"run 不存在: {job.run_id}")

        try:
            await self._ctx.run_engine.start(job.run_id)
            if job.kind == RUN_JOB_KIND_INGESTION:
                await self._ingestion.ingest(run)
                await self._ctx.run_engine.complete(job.run_id, "ready")
            elif job.kind == RUN_JOB_KIND_AGENT:
                await self._agent.run(run)
                await self._ctx.run_engine.complete(job.run_id, "done")
            else:
                await self._run_demo(job.run_id)
                await self._ctx.run_engine.complete(job.run_id, "done")
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            await self._ctx.run_engine.fail(job.run_id, message)
            raise

    async def _run_demo(self, run_id: str) -> None:
        """演示作业的假步骤,仅供 run-engine 链路自检。"""
        total = len(DEMO_STEPS)
        for index, step in enumerate(DEMO_STEPS, start=1):
            await self._ctx.run_engine.emit(
                run_id, "step", {"step": step, "index": index, "total": total}
            )
            await asyncio.sleep(0.2)
