"""FastAPI 依赖:上下文 / 数据库会话 / 当前用户(鉴权)/ 队列生产者。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from agent_core.auth import TokenClaims, UnauthorizedError
from agent_core.queue import RunJobProducer
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from rag_server.context import CoreContext


def get_ctx(request: Request) -> CoreContext:
    """进程上下文(启动时装配,挂在 app.state)。"""
    ctx: CoreContext = request.app.state.ctx
    return ctx


CtxDep = Annotated[CoreContext, Depends(get_ctx)]


def get_producer(request: Request) -> RunJobProducer:
    """任务队列生产者(HTTP 进程启动时建立)。"""
    producer: RunJobProducer = request.app.state.producer
    return producer


ProducerDep = Annotated[RunJobProducer, Depends(get_producer)]


async def get_session(ctx: CtxDep) -> AsyncIterator[AsyncSession]:
    """请求级数据库会话。"""
    async with ctx.session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _extract_token(request: Request) -> str:
    """从 Authorization: Bearer 或 SSE 兜底 ?access_token= 提取 token。"""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    query_token = request.query_params.get("access_token", "")
    if query_token:
        return query_token
    raise UnauthorizedError("缺少 token")


async def get_current_user(request: Request, ctx: CtxDep) -> int:
    """验签并解析本地用户 id(RS256/JWKS 或 HS256 兜底)。

    外部 IdP token(带 iss)走联合身份零接触映射;本地 token 直接用 sub。
    """
    token = _extract_token(request)
    claims: TokenClaims = ctx.jwt_verifier.verify(token)

    if claims.iss:
        return await ctx.federated.resolve_local_user_id(
            issuer=claims.iss,
            subject=claims.sub,
            username_hint=claims.username or None,
        )
    try:
        return int(claims.sub)
    except ValueError as e:
        raise UnauthorizedError("token sub 不是本地用户 id") from e


CurrentUserId = Annotated[int, Depends(get_current_user)]
