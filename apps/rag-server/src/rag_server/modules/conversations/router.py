"""conversations 路由:CRUD + 发消息(SSE 流式)。

与 Node 版对齐:发消息用**手写 SSE 帧**(POST 带 body,EventSource 不可用;
前端用 fetch + ReadableStream 读)。事件:token(逐字)、done(messageId + 引用)、error(出错收尾)。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from agent_core.run_engine import isoformat_ms
from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse, StreamingResponse

from rag_server.contracts import (
    AgentConversation,
    CreateConversationReq,
    SendMessageReq,
    wire,
)
from rag_server.db.models import Conversation, Message
from rag_server.deps import CtxDep, CurrentUserId
from rag_server.errors import BadRequestError
from rag_server.modules.conversations.chat import ChatService
from rag_server.modules.conversations.service import ConversationsService
from rag_server.shared.retrieval import RagRetriever
from rag_server.shared.sse import sse_frame

router = APIRouter(tags=["conversations"])


def _message_wire(m: Message) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": m.id,
        "conversationId": m.conversation_id,
        "role": m.role,
        "content": m.content,
        "createdAt": isoformat_ms(m.created_at),
    }
    if m.citations:
        data["citations"] = m.citations
    return data


def _conversation_wire(conv: Conversation, *, with_messages: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": conv.id,
        "title": conv.title,
        "createdAt": isoformat_ms(conv.created_at),
        "updatedAt": isoformat_ms(conv.updated_at),
    }
    if with_messages:
        data["messages"] = [_message_wire(m) for m in conv.messages]
    return wire(AgentConversation.from_dict(data))


def _service(ctx: CtxDep) -> ConversationsService:
    return ConversationsService(ctx.session_factory)


def _chat_service(ctx: CtxDep) -> ChatService:
    return ChatService(
        session_factory=ctx.session_factory,
        llm=ctx.llm,
        retriever=RagRetriever(session_factory=ctx.session_factory, llm=ctx.llm, vector=ctx.vector),
        conversations=ConversationsService(ctx.session_factory),
        settings=ctx.settings,
    )


@router.post("/conversations", status_code=201)
async def create(user_id: CurrentUserId, ctx: CtxDep, req: CreateConversationReq) -> JSONResponse:
    conv = await _service(ctx).create(user_id, req.title)
    return JSONResponse(status_code=201, content=_conversation_wire(conv, with_messages=False))


@router.get("/conversations")
async def list_conversations(user_id: CurrentUserId, ctx: CtxDep) -> JSONResponse:
    convs = await _service(ctx).list(user_id)
    return JSONResponse(content=[_conversation_wire(c, with_messages=False) for c in convs])


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int, user_id: CurrentUserId, ctx: CtxDep
) -> JSONResponse:
    conv = await _service(ctx).get(user_id, conversation_id)
    return JSONResponse(content=_conversation_wire(conv, with_messages=True))


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int, user_id: CurrentUserId, ctx: CtxDep
) -> Response:
    await _service(ctx).delete(user_id, conversation_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: int,
    req: SendMessageReq,
    user_id: CurrentUserId,
    ctx: CtxDep,
) -> StreamingResponse:
    """发消息,SSE 流式返回回答 + 引用。

    预检归属:在切到 SSE 头之前抛,失败可返回干净的 404 JSON。
    """
    query = (req.query or "").strip()
    if not query:
        raise BadRequestError("query 不能为空")
    if req.top_k is not None and not (1 <= req.top_k <= 20):
        raise BadRequestError("topK 需在 1-20 之间")
    await _service(ctx).ensure_owned(user_id, conversation_id)

    chat = _chat_service(ctx)

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for event in chat.stream_answer(
                user_id=user_id,
                conversation_id=conversation_id,
                query=query,
                top_k=req.top_k,
            ):
                yield sse_frame(str(event["type"]), event)
        except Exception as exc:
            yield sse_frame("error", {"message": str(exc) or "生成失败"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
