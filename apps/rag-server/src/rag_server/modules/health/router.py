"""GET /api/health —— 基础设施联通性检查(与 Node 版形状一致)。

并行探活 Postgres / Redis / Milvus;任一项 down → status=degraded,但仍 200。
LLM 不纳入(外部服务、按需调用,健康检查里 ping 会浪费 token)。
"""

from __future__ import annotations

from agent_core.health import check_components
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from rag_server.deps import CtxDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def check(ctx: CtxDep) -> JSONResponse:
    async def probe_postgres() -> None:
        async with ctx.session_factory() as session:
            await session.execute(text("SELECT 1"))

    async def probe_redis() -> None:
        await ctx.redis.ping()

    async def probe_milvus() -> None:
        await ctx.vector.ping()

    result = await check_components(
        {"postgres": probe_postgres, "redis": probe_redis, "milvus": probe_milvus}
    )
    return JSONResponse(content=result)
