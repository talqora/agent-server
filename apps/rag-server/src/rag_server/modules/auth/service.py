"""auth 业务:本地注册/登录(HS256 兜底路径,开发/本地用)+ 用户档案。

与 Node 版对齐(apps/node-server/src/modules/auth/auth.service.ts):
- 注册:用户名唯一(冲突 409 USERNAME_TAKEN);密码 bcrypt(10 轮)落库;
- 登录:"用户不存在"与"密码错误"同一句话回应,防账号枚举;
- 值级约束(proto3 表达不了)在业务层显式校验:用户名 3-64 [A-Za-z0-9_-]、密码 8-128、显示名 1-128。
"""

from __future__ import annotations

import re

import bcrypt
from agent_core.auth import sign_hs256
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import User
from rag_server.errors import ApiError, BadRequestError, ConflictError
from rag_server.settings import Settings

BCRYPT_ROUNDS = 10
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class AuthService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._settings = settings

    async def register(
        self, *, username: str, password: str, display_name: str
    ) -> tuple[str, User]:
        if not (3 <= len(username) <= 64) or not _USERNAME_RE.match(username):
            raise BadRequestError("用户名需为 3-64 位的字母、数字、下划线或连字符")
        if not (8 <= len(password) <= 128):
            raise BadRequestError("密码长度需为 8-128 位")
        if not (1 <= len(display_name) <= 128):
            raise BadRequestError("显示名长度需为 1-128 位")

        async with self._sf() as session:
            taken = await session.scalar(select(User.id).where(User.username == username))
            if taken is not None:
                raise ConflictError("用户名已被注册", code="USERNAME_TAKEN")

            password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
            ).decode("utf-8")
            user = User(
                username=username,
                password_hash=password_hash,
                display_name=display_name,
                role_code="USER",
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return self._sign_token(user), user

    async def login(self, *, username: str, password: str) -> tuple[str, User]:
        async with self._sf() as session:
            user = await session.scalar(select(User).where(User.username == username))
        # 用同一句话回应"用户不存在"和"密码错误",防止账号枚举
        if user is None:
            raise _invalid_credentials()
        ok = bcrypt.checkpw(password.encode("utf-8"), user.password_hash.encode("utf-8"))
        if not ok:
            raise _invalid_credentials()
        return self._sign_token(user), user

    async def get_profile(self, user_id: int) -> User:
        async with self._sf() as session:
            user = await session.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise ApiError(401, "用户不存在", code="USER_NOT_FOUND")
        return user

    def _sign_token(self, user: User) -> str:
        return sign_hs256(
            secret=self._settings.jwt_secret,
            sub=str(user.id),
            username=user.username,
            role=user.role_code,
            expire_seconds=self._settings.jwt_expire_seconds,
        )


def _invalid_credentials() -> ApiError:
    return ApiError(401, "用户名或密码错误", code="INVALID_CREDENTIALS")
