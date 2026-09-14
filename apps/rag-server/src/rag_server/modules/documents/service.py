"""文档服务:上传(存盘 + 建行 + 入队摄取)/ 列表 / 详情 / 删除(清 Milvus + 磁盘)。

对齐 Node 版(apps/node-server/src/modules/documents/documents.service.ts):
- 上传:校验类型/大小 → 落盘 → Document(status=queued)→ 建 ingestion run → 入队 → 立即返回;
- 删除顺序:Milvus 向量先清 → Postgres 行删(chunks 级联)→ 磁盘文件尽力删。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import uuid4

from agent_core.queue import RUN_JOB_KIND_INGESTION, RunJob, RunJobProducer
from agent_core.run_engine import RunEngine
from agent_core.vector import MilvusVectorStore
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rag_server.db.models import Document
from rag_server.errors import BadRequestError, NotFoundError
from rag_server.modules.documents.parser import (
    SUPPORTED_HINT,
    is_supported,
)
from rag_server.settings import Settings

logger = logging.getLogger("rag_server.documents")


def normalize_filename(name: str) -> str:
    """multipart 文件名兼容:部分解析器按 latin-1 解 UTF-8 字节(中文乱码)→ 还原。

    ASCII 名重解码是 no-op,安全(与 Node 版同一修复)。
    """
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


class DocumentsService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        vector: MilvusVectorStore,
        run_engine: RunEngine,
        producer: RunJobProducer,
        settings: Settings,
    ) -> None:
        self._sf = session_factory
        self._vector = vector
        self._run_engine = run_engine
        self._producer = producer
        self._settings = settings

    async def upload(
        self, *, user_id: int, filename: str, mime_type: str, data: bytes
    ) -> tuple[int, str]:
        """存盘 → 建 Document(queued)→ 起摄取 run 入队;不在请求线程里做解析。"""
        original_name = normalize_filename(filename)
        if not is_supported(original_name):
            raise BadRequestError(f"不支持的文件类型({SUPPORTED_HINT})")
        if len(data) > self._settings.document_max_bytes:
            raise BadRequestError(f"文件过大,上限 {self._settings.document_max_bytes} 字节")

        storage_dir = Path(self._settings.document_storage_dir) / str(user_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{uuid4()}-{os.path.basename(original_name)}"
        await asyncio.to_thread(storage_path.write_bytes, data)

        async with self._sf() as session:
            doc = Document(
                user_id=user_id,
                filename=original_name,
                mime_type=mime_type,
                size_bytes=len(data),
                storage_path=str(storage_path),
                status="queued",
            )
            session.add(doc)
            await session.commit()
            await session.refresh(doc)

        run = await self._run_engine.create_run(
            user_id=user_id,
            kind="ingestion",
            task=f"ingest:{original_name}"[:255],
            ref_id=str(doc.id),
        )
        await self._producer.send(
            RunJob(run_id=run.run_id, user_id=user_id, kind=RUN_JOB_KIND_INGESTION)
        )
        logger.info("文档已上传 id=%s run=%s file=%s", doc.id, run.run_id, original_name)
        return doc.id, run.run_id

    async def list(self, user_id: int) -> list[Document]:
        async with self._sf() as session:
            rows = await session.scalars(
                select(Document)
                .where(Document.user_id == user_id)
                .order_by(Document.created_at.desc())
            )
            return list(rows)

    async def get(self, user_id: int, document_id: int) -> Document:
        async with self._sf() as session:
            doc = await session.scalar(select(Document).where(Document.id == document_id))
            if doc is None or doc.user_id != user_id:
                raise NotFoundError("文档不存在或无权访问")
            return doc

    async def delete(self, user_id: int, document_id: int) -> None:
        """删文档:Milvus 向量先清 → Postgres 行删(chunks 级联)→ 磁盘文件尽力删。"""
        doc = await self.get(user_id, document_id)
        await self._vector.delete_by_document(doc.id)
        async with self._sf() as session:
            await session.execute(delete(Document).where(Document.id == doc.id))
            await session.commit()
        try:
            await asyncio.to_thread(Path(doc.storage_path).unlink, True)  # missing_ok=True
        except OSError as exc:  # 文件可能本就不存在;其他错误仅日志不抛
            logger.warning("删除文档 %s 的磁盘文件失败: %s", document_id, exc)
        logger.info("文档已删除 id=%s", document_id)
