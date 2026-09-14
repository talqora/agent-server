"""文档摄取:解析 → 切分 → 批量 embedding → 双写(PG chunk + Milvus 向量)。

在 worker 进程内由 RunProcessor 调度,逐步经 run-engine 广播进度。
双写顺序:先写 Postgres DocumentChunk(拿 chunkId)→ upsert Milvus(payload 带 chunk_id);
Milvus 失败则整个 job 失败重试。重试幂等靠开写前按 document_id 清场两边旧数据。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from uuid import uuid4

from agent_core.llm import LlmClient
from agent_core.run_engine import RunEngine, RunRecord
from agent_core.vector import ChunkPoint, MilvusVectorStore
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import Document, DocumentChunk
from rag_server.modules.documents.parser import parse_to_text
from rag_server.modules.documents.splitter import SplitOptions, estimate_tokens, split_text
from rag_server.settings import Settings

logger = logging.getLogger("rag_server.ingestion")


class IngestionService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        llm: LlmClient,
        vector: MilvusVectorStore,
        run_engine: RunEngine,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._llm = llm
        self._vector = vector
        self._run_engine = run_engine
        self._settings = settings

    async def ingest(self, run: RunRecord) -> None:
        document_id = int(run.ref_id or 0)
        doc = await self._get_document(document_id, run.user_id)

        try:
            await self._set_document_status(document_id, status="processing", error_msg=None)

            # ① 解析(CPU 活,to_thread)
            await self._run_engine.emit(run.run_id, "step", {"step": "parsing"})
            raw = await asyncio.to_thread(Path(doc.storage_path).read_bytes)
            text = await asyncio.to_thread(parse_to_text, raw, doc.filename)

            # ② 切分
            chunks = split_text(
                text,
                SplitOptions(
                    chunk_size=self._settings.chunk_size,
                    chunk_overlap=self._settings.chunk_overlap,
                ),
            )
            await self._run_engine.emit(
                run.run_id, "step", {"step": "chunking", "chunks": len(chunks)}
            )

            # ③ 重试幂等:开写前清掉本文档可能残留的两边旧数据
            await self._vector.delete_by_document(document_id)
            await self._clear_chunks(document_id)

            # ④ 批量 embedding + 双写
            batch_size = self._settings.embed_batch
            written = 0
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                vectors = await self._llm.embed(batch)
                points: list[ChunkPoint] = []
                for offset, (content, vector) in enumerate(zip(batch, vectors, strict=True)):
                    chunk_index = start + offset
                    point_id = str(uuid4())
                    chunk_id = await self._create_chunk(
                        document_id=document_id,
                        user_id=doc.user_id,
                        chunk_index=chunk_index,
                        content=content,
                        vector_id=point_id,
                    )
                    points.append(
                        ChunkPoint(
                            id=point_id,
                            vector=vector,
                            payload={
                                "user_id": doc.user_id,
                                "document_id": document_id,
                                "chunk_id": chunk_id,
                                "chunk_index": chunk_index,
                            },
                        )
                    )
                await self._vector.upsert_chunks(points)
                written += len(batch)
                await self._run_engine.emit(
                    run.run_id,
                    "step",
                    {"step": "embedding", "done": written, "total": len(chunks)},
                )

            # ⑤ 完成
            await self._set_document_status(document_id, status="ready", chunk_count=len(chunks))
            logger.info("摄取完成 document=%s chunks=%s", document_id, len(chunks))
        except Exception as exc:
            message = (str(exc) or exc.__class__.__name__)[:1000]
            await self._set_document_status(document_id, status="failed", error_msg=message)
            raise

    # ── 内部:每步一个短事务 ──

    async def _get_document(self, document_id: int, user_id: int) -> Document:
        async with self._sf() as session:
            doc = await session.scalar(select(Document).where(Document.id == document_id))
            if doc is None or doc.user_id != user_id:
                raise RuntimeError(f"摄取目标文档不存在或归属不符: {document_id}")
            return doc

    async def _set_document_status(
        self,
        document_id: int,
        *,
        status: str,
        error_msg: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        values: dict[str, object] = {"status": status, "error_msg": error_msg}
        if chunk_count is not None:
            values["chunk_count"] = chunk_count
        async with self._sf() as session:
            await session.execute(
                update(Document).where(Document.id == document_id).values(**values)
            )
            await session.commit()

    async def _clear_chunks(self, document_id: int) -> None:
        async with self._sf() as session:
            await session.execute(
                delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            await session.commit()

    async def _create_chunk(
        self,
        *,
        document_id: int,
        user_id: int,
        chunk_index: int,
        content: str,
        vector_id: str,
    ) -> int:
        async with self._sf() as session:
            chunk = DocumentChunk(
                document_id=document_id,
                user_id=user_id,
                chunk_index=chunk_index,
                content=content,
                token_count=estimate_tokens(content),
                vector_id=vector_id,
            )
            session.add(chunk)
            await session.commit()
            await session.refresh(chunk)
            return chunk.id
