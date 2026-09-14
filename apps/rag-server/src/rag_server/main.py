"""HTTP 进程入口:FastAPI app 装配 + uvicorn 启动。

角色:接请求 + 持有 SSE 连接;重活入队(Pulsar)交给 worker 进程。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from agent_core.logging import setup_logging
from agent_core.queue import RunJobProducer
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rag_server import __version__
from rag_server.context import build_core, close_core
from rag_server.errors import install_error_handlers
from rag_server.modules.agent.router import router as agent_router
from rag_server.modules.auth.router import router as auth_router
from rag_server.modules.conversations.router import router as conversations_router
from rag_server.modules.documents.router import router as documents_router
from rag_server.modules.health.router import router as health_router
from rag_server.modules.runs.router import router as runs_router
from rag_server.modules.task_sessions.router import router as task_sessions_router
from rag_server.settings import get_settings

logger = logging.getLogger("rag_server.main")


def _install_cors(app: FastAPI, env: str, origins: list[str]) -> None:
    """CORS 与 Node 版行为对齐:
    - 白名单非空 → 精确匹配;
    - 空白名单 + 非生产 → 反射任意 origin(开发友好);
    - 空白名单 + 生产 → 不加中间件(等同拒所有跨源)。
    """
    common: dict[str, Any] = {
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
        "expose_headers": ["Last-Event-ID"],
    }
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, **common)
    elif env != "production":
        app.add_middleware(CORSMiddleware, allow_origin_regex=".*", **common)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = await build_core(settings)
        producer = RunJobProducer(settings.pulsar_url, settings.pulsar_topic)
        await producer.start()
        app.state.ctx = ctx
        app.state.producer = producer
        try:
            yield
        finally:
            await producer.close()
            await close_core(ctx)

    app = FastAPI(title="rag-server", version=__version__, lifespan=lifespan)
    _install_cors(app, settings.env, settings.cors_origin_list())
    install_error_handlers(app)

    # 路由:与 Node 版路径逐一对应(全局前缀 /api)
    api_prefix = "/api"
    app.include_router(health_router, prefix=api_prefix)
    app.include_router(auth_router, prefix=api_prefix)
    app.include_router(runs_router, prefix=api_prefix)
    app.include_router(documents_router, prefix=api_prefix)
    app.include_router(conversations_router, prefix=api_prefix)
    app.include_router(task_sessions_router, prefix=api_prefix)
    app.include_router(agent_router, prefix=api_prefix)
    return app


def run() -> None:
    """console script 入口:rag-http。"""
    settings = get_settings()
    setup_logging("rag-http", settings.log_level)
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=settings.port,
        log_level=settings.log_level.lower(),
        # SSE 是长连接:滚动重启时最多等 10s 优雅收尾,超时强断(客户端会重连补发)
        timeout_graceful_shutdown=10,
    )
