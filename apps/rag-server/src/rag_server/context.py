"""进程上下文装配:HTTP 与 worker 两个入口共享的核心依赖。

装配顺序 = 依赖顺序;关闭顺序相反。所有连接在启动时建立(配置即启动断言)。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agent_core.auth import JwtVerifier
from agent_core.db import make_engine, make_session_factory
from agent_core.events import EventBus
from agent_core.federated import FederatedIdentity
from agent_core.llm import LlmClient
from agent_core.redis import RedisClient
from agent_core.run_engine import RunEngine
from agent_core.vector import MilvusVectorStore
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from rag_server.db.adapters import SqlAlchemyRunRepository, SqlAlchemyUserStore
from rag_server.settings import Settings

logger = logging.getLogger("rag_server.context")


@dataclass
class CoreContext:
    """两个角色(HTTP / worker)共享的核心依赖。"""

    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: RedisClient
    event_bus: EventBus
    jwt_verifier: JwtVerifier
    federated: FederatedIdentity
    run_engine: RunEngine
    llm: LlmClient
    vector: MilvusVectorStore


async def build_core(settings: Settings) -> CoreContext:
    """建立核心上下文:DB / Redis / Milvus / LLM / 鉴权 / 运行引擎。"""
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    redis = RedisClient(settings.redis_url)
    await redis.connect()

    event_bus = EventBus(redis, channel_prefix=settings.service_name)
    run_engine = RunEngine(repo=SqlAlchemyRunRepository(session_factory), bus=event_bus)

    vector = MilvusVectorStore(
        address=settings.milvus_address,
        token=settings.milvus_token,
        collection=settings.milvus_collection,
        vector_size=settings.milvus_vector_size,
    )
    # 幂等:建集合(如缺)+ 索引 + load(检索前置条件);Milvus 不可达 → 启动失败(同 Node 版)
    await vector.ensure_collection()

    llm = LlmClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        chat_model=settings.llm_chat_model,
        embed_model=settings.llm_embed_model,
        timeout_s=settings.llm_timeout_seconds,
    )

    jwt_verifier = JwtVerifier(
        jwks_uri=settings.oauth_jwks_uri,
        issuer=settings.oauth_issuer,
        hs_secret=settings.jwt_secret,
    )
    federated = FederatedIdentity(SqlAlchemyUserStore(session_factory))

    logger.info(
        "核心上下文就绪(env=%s, db=%s, milvus=%s/%s)",
        settings.env,
        engine.url.render_as_string(hide_password=True),
        settings.milvus_address,
        settings.milvus_collection,
    )
    return CoreContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        redis=redis,
        event_bus=event_bus,
        jwt_verifier=jwt_verifier,
        federated=federated,
        run_engine=run_engine,
        llm=llm,
        vector=vector,
    )


async def close_core(ctx: CoreContext) -> None:
    """释放核心上下文资源(顺序与建立相反)。"""
    await ctx.llm.close()
    await ctx.redis.close()
    await ctx.engine.dispose()
    logger.info("核心上下文已释放")
