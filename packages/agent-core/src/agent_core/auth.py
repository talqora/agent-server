"""JWT 双模验签:RS256(JWKS,our-chat IdP)+ HS256(本地兜底),按 header.alg 分发。

与 Node 版行为对齐(apps/node-server/src/modules/auth/jwt.strategy.ts):
- RS256:用 JWKS 公钥验签,强制校验 iss/aud(资源标识 = agent-server);
- HS256:共享密钥验签(本地注册/登录签发,开发/兜底路径);
- 时钟容差 30s;
- 不支持其他 alg。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import jwt
from jwt import PyJWKClient

RESOURCE_AUDIENCE = "agent-server"


class UnauthorizedError(Exception):
    """验签失败/无法解析 → 调用方转 401。"""


@dataclass(frozen=True)
class TokenClaims:
    """验签通过后的标准声明(与载荷解耦,避免业务散读原始 dict)。"""

    sub: str
    iss: str | None
    username: str
    role: str
    scope: tuple[str, ...]
    raw: dict[str, Any] = field(repr=False, default_factory=dict)


def sign_hs256(
    *,
    secret: str,
    sub: str,
    username: str,
    role: str,
    expire_seconds: int,
) -> str:
    """本地登录签发 HS256 token(仅开发/兜底路径使用)。"""
    now = int(time.time())
    return jwt.encode(
        {"sub": sub, "username": username, "role": role, "iat": now, "exp": now + expire_seconds},
        secret,
        algorithm="HS256",
    )


class JwtVerifier:
    def __init__(
        self,
        *,
        jwks_uri: str = "",
        issuer: str = "",
        hs_secret: str = "dev-secret",
        audience: str = RESOURCE_AUDIENCE,
        clock_tolerance_s: int = 30,
    ) -> None:
        self._issuer = issuer or None
        self._hs_secret = hs_secret
        self._audience = audience
        self._leeway = clock_tolerance_s
        self._jwks_client = PyJWKClient(jwks_uri, cache_keys=True) if jwks_uri else None

    def verify(self, token: str) -> TokenClaims:
        """验签并返回标准声明;任何失败抛 UnauthorizedError。"""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:  # pragma: no cover - 格式错误路径
            raise UnauthorizedError("token 无法解析") from e

        alg = header.get("alg")
        if alg == "RS256":
            payload = self._verify_rs256(token)
        elif alg == "HS256":
            payload = self._verify_hs256(token)
        else:
            raise UnauthorizedError(f"不支持的 alg: {alg}")

        scope_raw = payload.get("scope") or ""
        return TokenClaims(
            sub=str(payload.get("sub", "")),
            iss=payload.get("iss"),
            username=str(payload.get("username") or payload.get("preferred_username") or ""),
            role=str(payload.get("role") or "USER"),
            scope=tuple(scope_raw.split()),
            raw=dict(payload),
        )

    def _verify_rs256(self, token: str) -> dict[str, Any]:
        if self._jwks_client is None:
            raise UnauthorizedError("收到 RS256 token 但未配置 JWKS(OAUTH_JWKS_URI)")
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise UnauthorizedError(f"RS256 验签失败: {e}") from e

    def _verify_hs256(self, token: str) -> dict[str, Any]:
        try:
            return jwt.decode(
                token,
                self._hs_secret,
                algorithms=["HS256"],
                leeway=self._leeway,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as e:
            raise UnauthorizedError(f"HS256 验签失败: {e}") from e
