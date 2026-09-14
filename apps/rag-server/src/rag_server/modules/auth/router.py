"""auth 路由:注册 / 登录 / 当前用户(与 Node 版路径与状态码一致)。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from rag_server.contracts import AgentUser, AuthResp, LoginReq, RegisterReq, wire
from rag_server.db.models import User
from rag_server.deps import CtxDep, CurrentUserId
from rag_server.modules.auth.service import AuthService

router = APIRouter(tags=["auth"])


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "displayName": user.display_name,
        "roleCode": user.role_code,
    }


def _service(ctx: CtxDep) -> AuthService:
    return AuthService(session_factory=ctx.session_factory, settings=ctx.settings)


@router.post("/auth/register", status_code=201)
async def register(ctx: CtxDep, req: RegisterReq) -> JSONResponse:
    token, user = await _service(ctx).register(
        username=req.username, password=req.password, display_name=req.display_name
    )
    body = wire(AuthResp.from_dict({"token": token, "user": _user_payload(user)}))
    return JSONResponse(status_code=201, content=body)


@router.post("/auth/login")
async def login(ctx: CtxDep, req: LoginReq) -> JSONResponse:
    token, user = await _service(ctx).login(username=req.username, password=req.password)
    body = wire(AuthResp.from_dict({"token": token, "user": _user_payload(user)}))
    return JSONResponse(content=body)


@router.get("/auth/me")
async def me(user_id: CurrentUserId, ctx: CtxDep) -> JSONResponse:
    user = await _service(ctx).get_profile(user_id)
    return JSONResponse(content=wire(AgentUser.from_dict(_user_payload(user))))
