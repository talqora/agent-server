"""联合身份:外部 IdP(our-chat)的 (issuer, subject) → 本地用户 id 的零接触映射。

与 Node 版对齐(apps/node-server/src/modules/auth/federated-identity.service.ts):
- 不复用外部 sub 作本地主键(号段不同,会撞号);
- 首次见到某外部主体即建本地账;并发首见靠唯一约束冲突回查收敛(幂等);
- 命中后进程内缓存(联合用户建立后不会改 id,无需失效)。
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy.exc import IntegrityError


class UserStore(Protocol):
    """持久化端口:由各服务用自己的 ORM 模型实现(见服务内 adapters)。"""

    async def find_by_issuer_subject(self, issuer: str, subject: str) -> int | None: ...

    async def create_federated_user(
        self,
        *,
        issuer: str,
        subject: str,
        username: str,
        display_name: str,
        role_code: str,
    ) -> int: ...


class FederatedIdentity:
    def __init__(self, store: UserStore, *, role_code: str = "USER") -> None:
        self._store = store
        self._role_code = role_code
        self._cache: dict[tuple[str, str], int] = {}
        self._logger = logging.getLogger("agent_core.federated")

    async def resolve_local_user_id(
        self, *, issuer: str, subject: str, username_hint: str | None = None
    ) -> int:
        key = (issuer, subject)
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        existing = await self._store.find_by_issuer_subject(issuer, subject)
        if existing is None:
            fallback = f"oc_{subject}"
            try:
                existing = await self._store.create_federated_user(
                    issuer=issuer,
                    subject=subject,
                    username=username_hint or fallback,
                    display_name=username_hint or fallback,
                    role_code=self._role_code,
                )
                self._logger.info("zero-touch 建联合用户 %s/%s → id=%s", issuer, subject, existing)
            except IntegrityError:
                # 并发首见:另一请求已抢先建好,(issuer,subject) 唯一约束冲突 → 回查
                existing = await self._store.find_by_issuer_subject(issuer, subject)
                if existing is None:
                    raise

        self._cache[key] = existing
        return existing
