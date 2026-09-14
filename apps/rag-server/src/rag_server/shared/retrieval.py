"""RAG 检索器 —— 全应用唯一的向量检索入口。

多租户隔离纪律(与 Node 版对齐):
检索只能走这里,且只经 vector.search_by_user(user_id 过滤写死在 agent-core 那一层)。
禁止任何 router/service 自己拼 Milvus filter——从代码结构上杜绝漏过滤导致的越权泄露。
"""

from __future__ import annotations

from dataclasses import dataclass

from agent_core.llm import LlmClient
from agent_core.vector import MilvusVectorStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import DocumentChunk


@dataclass(frozen=True)
class RetrievedChunk:
    """一条检索命中:回指 Postgres chunk 的原文 + Milvus 相似度分。"""

    chunk_id: int
    document_id: int
    chunk_index: int
    content: str
    score: float


class RagRetriever:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LlmClient,
        vector: MilvusVectorStore,
    ) -> None:
        self._sf = session_factory
        self._llm = llm
        self._vector = vector

    async def retrieve(self, user_id: int, query: str, top_k: int) -> list[RetrievedChunk]:
        """query 向量化 → 按 user 检索 top-k → 回 Postgres 取原文,保持相似度降序。"""
        vectors = await self._llm.embed(query)
        hits = await self._vector.search_by_user(vectors[0], user_id, top_k)
        if not hits:
            return []

        chunk_ids = [h.payload["chunk_id"] for h in hits]
        async with self._sf() as session:
            rows = (
                await session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))
            ).all()
        by_id = {row.id: row for row in rows}

        # 按 Milvus 命中顺序(相似度降序)输出;Postgres 已删的 chunk 跳过
        result: list[RetrievedChunk] = []
        for hit in hits:
            row = by_id.get(hit.payload["chunk_id"])
            if row is None:
                continue
            result.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    chunk_index=row.chunk_index,
                    content=row.content,
                    score=hit.score,
                )
            )
        return result
