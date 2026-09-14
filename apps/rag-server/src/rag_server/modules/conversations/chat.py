"""RAG 对话编排:存提问 → 检索(强制 user 过滤)→ 拼 prompt(system+资料+历史+提问)
→ 流式生成并逐 token 产出 → 存 assistant 回答 + citations。

全程在 HTTP 进程同步完成(检索快、生成流式),不走 worker(与 Node 版一致)。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from agent_core.llm import ChatCompletionMessageParam, LlmClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.contracts import Citation
from rag_server.db.models import Conversation, Message
from rag_server.modules.conversations.service import ConversationsService
from rag_server.settings import Settings
from rag_server.shared.retrieval import RagRetriever, RetrievedChunk

logger = logging.getLogger("rag_server.chat")

SYSTEM_PROMPT = "\n".join(
    [
        "你是一个个人知识助手,只能依据下方「资料」回答用户问题。",
        '若资料不足以回答,如实说明"资料中没有相关内容",不要编造。',
        "引用资料时用 [n] 标注来源编号(对应资料前的序号)。",
    ]
)


class ChatService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LlmClient,
        retriever: RagRetriever,
        conversations: ConversationsService,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._llm = llm
        self._retriever = retriever
        self._conversations = conversations
        self._settings = settings

    async def stream_answer(
        self, *, user_id: int, conversation_id: int, query: str, top_k: int | None
    ) -> AsyncIterator[dict[str, Any]]:
        """产出 SSE 事件 dict:``{type:'token',value}`` / ``{type:'done',messageId,citations}``。"""
        conv = await self._conversations.ensure_owned(user_id, conversation_id)

        # 取历史(在写入本轮提问之前),最多最近 N 条,按时间升序拼 prompt
        async with self._sf() as session:
            history = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.created_at.desc())
                        .limit(self._settings.history_limit)
                    )
                ).all()
            )
        history.reverse()

        async with self._sf() as session:
            session.add(Message(conversation_id=conversation_id, role="user", content=query))
            await session.commit()

        chunks = await self._retriever.retrieve(user_id, query, top_k or self._settings.rag_top_k)
        messages = self._build_messages(chunks, history, query)

        answer_parts: list[str] = []
        async for token in self._llm.chat_stream(messages):
            answer_parts.append(token)
            yield {"type": "token", "value": token}
        answer = "".join(answer_parts)

        citations = [
            Citation(chunk_id=c.chunk_id, document_id=c.document_id, score=c.score) for c in chunks
        ]
        citation_payload = [c.to_dict() for c in citations]

        async with self._sf() as session:
            saved = Message(
                conversation_id=conversation_id,
                role="assistant",
                content=answer,
                citations=citation_payload,
            )
            session.add(saved)
            await session.commit()
            await session.refresh(saved)

        # 首轮提问顺手把默认标题改成问题摘要;并 bump updatedAt 供会话列表排序
        async with self._sf() as session:
            if conv.title == "新对话":
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(title=query[:64])
                )
            else:
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(updated_at=func.now())
                )
            await session.commit()

        logger.info(
            "对话生成完成 conversation=%s chunks=%s len=%s",
            conversation_id,
            len(chunks),
            len(answer),
        )
        yield {"type": "done", "messageId": saved.id, "citations": citation_payload}

    def _build_messages(
        self,
        chunks: list[RetrievedChunk],
        history: list[Message],
        query: str,
    ) -> list[ChatCompletionMessageParam]:
        """system(含资料)+ 历史 + 本轮提问。"""
        if not chunks:
            context = "(无检索到的资料)"
        else:
            context = "\n\n".join(
                f"[{i + 1}] (文档 {c.document_id}) {c.content}" for i, c in enumerate(chunks)
            )
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n资料:\n{context}"}
        ]
        for m in history:
            if m.role == "assistant":
                messages.append({"role": "assistant", "content": m.content})
            else:
                messages.append({"role": "user", "content": m.content})
        messages.append({"role": "user", "content": query})
        return messages
