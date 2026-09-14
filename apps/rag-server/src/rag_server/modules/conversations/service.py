"""会话与消息的持久化层(纯 CRUD,无 LLM/检索逻辑)。

所有读写都按 user_id 做归属校验——多租户隔离不能只靠检索过滤,会话/消息本身
也必须按 user 限定(与 Node 版一致)。
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import Conversation
from rag_server.errors import NotFoundError


class ConversationsService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def create(self, user_id: int, title: str | None) -> Conversation:
        async with self._sf() as session:
            conv = Conversation(user_id=user_id, title=title or "新对话")
            session.add(conv)
            await session.commit()
            await session.refresh(conv)
            return conv

    async def list(self, user_id: int) -> list[Conversation]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(Conversation)
                .where(Conversation.user_id == user_id)
                .order_by(Conversation.updated_at.desc())
            )
            return list(rows)

    async def get(self, user_id: int, conversation_id: int) -> Conversation:
        """取会话 + 全量消息(selectin 预加载,按时间升序),含归属校验。"""
        async with self._sf() as session:
            conv = await session.scalar(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            if conv is None or conv.user_id != user_id:
                raise NotFoundError("会话不存在或无权访问")
            return conv

    async def ensure_owned(self, user_id: int, conversation_id: int) -> Conversation:
        """仅校验归属并返回会话本身(不拉消息),供 ChatService / 路由预检用。"""
        async with self._sf() as session:
            conv = await session.scalar(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            if conv is None or conv.user_id != user_id:
                raise NotFoundError("会话不存在或无权访问")
            return conv

    async def delete(self, user_id: int, conversation_id: int) -> None:
        conv = await self.ensure_owned(user_id, conversation_id)
        async with self._sf() as session:
            await session.execute(delete(Conversation).where(Conversation.id == conv.id))
            await session.commit()
