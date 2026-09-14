"""工具注册表:集中声明 agent 可用的全部工具,并按名取用。

与 Node 版对齐(apps/node-server/src/modules/agent/tool.registry.ts):
- 每个工具是 {schema, run} 对,捕获注入的 Retriever / Session / LLM 依赖;
- 所有读用户数据的工具都按 ctx.user_id 过滤(多租户隔离);
- 语义检索复用唯一检索入口 RagRetriever(user 过滤写死在其中)。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent_core.llm import ChatCompletionMessageParam, LlmClient
from openai.types.chat import ChatCompletionToolParam
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import Document, DocumentChunk
from rag_server.shared.retrieval import RagRetriever

# 喂回模型的工具结果上限,防单条工具输出塞爆上下文
MAX_DOC_CHARS = 6000


@dataclass(frozen=True)
class ToolContext:
    user_id: int
    run_id: str


@dataclass(frozen=True)
class AgentTool:
    name: str
    schema: ChatCompletionToolParam
    run: Callable[[dict[str, Any], ToolContext], Awaitable[str]]


def _as_string(value: Any) -> str:
    """LLM 给的工具参数是任意 JSON,非字符串一律当空串,避免 [object Object]。"""
    return value if isinstance(value, str) else ""


class ToolRegistry:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LlmClient,
        retriever: RagRetriever,
        default_top_k: int,
    ) -> None:
        self._sf = session_factory
        self._llm = llm
        self._retriever = retriever
        self._default_top_k = default_top_k
        self._tools: dict[str, AgentTool] = {
            t.name: t
            for t in (
                self._retrieve_knowledge(),
                self._list_documents(),
                self._summarize_document(),
                self._organize(),
            )
        }

    def schemas(self) -> list[ChatCompletionToolParam]:
        """全部工具的 schema,直接喂给 chat_with_tools。"""
        return [t.schema for t in self._tools.values()]

    def get(self, name: str) -> AgentTool | None:
        return self._tools.get(name)

    # ── 工具实现 ──

    def _retrieve_knowledge(self) -> AgentTool:
        async def run(args: dict[str, Any], ctx: ToolContext) -> str:
            query = _as_string(args.get("query")).strip()
            if not query:
                return "错误:query 不能为空"
            chunks = await self._retriever.retrieve(ctx.user_id, query, self._default_top_k)
            if not chunks:
                return "没有检索到相关资料。"
            return "\n\n".join(
                f"[{i + 1}] (文档 {c.document_id}) {c.content}" for i, c in enumerate(chunks)
            )

        return AgentTool(
            name="retrieve_knowledge",
            schema={
                "type": "function",
                "function": {
                    "name": "retrieve_knowledge",
                    "description": (
                        "在用户的个人知识库中按语义检索相关片段,返回命中的资料文本及其文档编号。"
                        "回答涉及资料内容的问题时优先用它。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "检索关键词或问题"}
                        },
                        "required": ["query"],
                    },
                },
            },
            run=run,
        )

    def _list_documents(self) -> AgentTool:
        async def run(_args: dict[str, Any], ctx: ToolContext) -> str:
            async with self._sf() as session:
                docs = (
                    await session.scalars(
                        select(Document)
                        .where(Document.user_id == ctx.user_id)
                        .order_by(Document.created_at.desc())
                    )
                ).all()
            if not docs:
                return "用户还没有上传任何文档。"
            return "\n".join(
                f"文档 {d.id}:{d.filename}(状态 {d.status},{d.chunk_count} 片段)" for d in docs
            )

        return AgentTool(
            name="list_documents",
            schema={
                "type": "function",
                "function": {
                    "name": "list_documents",
                    "description": (
                        "列出用户已上传的全部文档(编号、文件名、摄取状态、片段数)。"
                        "需要先了解用户有哪些资料时调用。"
                    ),
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            run=run,
        )

    def _summarize_document(self) -> AgentTool:
        async def run(args: dict[str, Any], ctx: ToolContext) -> str:
            try:
                document_id = int(args.get("documentId"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return "错误:documentId 必须是整数"
            async with self._sf() as session:
                doc = await session.scalar(
                    select(Document).where(
                        Document.id == document_id, Document.user_id == ctx.user_id
                    )
                )
                if doc is None:
                    return f"错误:文档 {document_id} 不存在或无权访问"
                chunks = (
                    await session.scalars(
                        select(DocumentChunk)
                        .where(
                            DocumentChunk.document_id == document_id,
                            DocumentChunk.user_id == ctx.user_id,
                        )
                        .order_by(DocumentChunk.chunk_index)
                        .limit(20)
                    )
                ).all()
            if not chunks:
                return f"文档 {document_id}({doc.filename})还没有可用片段(可能尚未摄取完成)。"
            text = "\n".join(c.content for c in chunks)[:MAX_DOC_CHARS]
            messages: list[ChatCompletionMessageParam] = [
                {
                    "role": "system",
                    "content": "用 3-5 句话概括下面文档内容的要点,只输出概括本身。",
                },
                {"role": "user", "content": text},
            ]
            summary = await self._llm.chat(messages)
            return f"文档 {document_id}({doc.filename})摘要:\n{summary}"

        return AgentTool(
            name="summarize_document",
            schema={
                "type": "function",
                "function": {
                    "name": "summarize_document",
                    "description": "概括某一个文档的要点。传入 list_documents 返回的文档编号。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "documentId": {"type": "integer", "description": "文档编号"}
                        },
                        "required": ["documentId"],
                    },
                },
            },
            run=run,
        )

    def _organize(self) -> AgentTool:
        async def run(args: dict[str, Any], ctx: ToolContext) -> str:
            keyword = _as_string(args.get("keyword")).strip()
            if not keyword:
                return "错误:keyword 不能为空"
            async with self._sf() as session:
                docs = (
                    await session.scalars(
                        select(Document)
                        .where(
                            Document.user_id == ctx.user_id,
                            Document.filename.ilike(f"%{keyword}%"),
                        )
                        .order_by(Document.created_at.desc())
                    )
                ).all()
            if not docs:
                return f"没有文件名包含「{keyword}」的文档。"
            return "\n".join(
                f"文档 {d.id}:{d.filename}(状态 {d.status},{d.chunk_count} 片段)" for d in docs
            )

        return AgentTool(
            name="organize",
            schema={
                "type": "function",
                "function": {
                    "name": "organize",
                    "description": (
                        '按关键词筛选用户文档(匹配文件名),用于把"某一类"文档先圈出来,'
                        "再逐个 summarize_document。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "用于匹配文件名的关键词",
                            }
                        },
                        "required": ["keyword"],
                    },
                },
            },
            run=run,
        )
