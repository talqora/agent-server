"""documents 路由:上传 / 列表 / 详情 / 删除(与 Node 版路径与状态码一致)。"""

from __future__ import annotations

from typing import Annotated, Any

from agent_core.run_engine import isoformat_ms
from fastapi import APIRouter, File, Response, UploadFile
from fastapi.responses import JSONResponse

from rag_server.contracts import AgentDocument, UploadDocResp, wire
from rag_server.db.models import Document
from rag_server.deps import CtxDep, CurrentUserId, ProducerDep
from rag_server.modules.documents.service import DocumentsService

router = APIRouter(tags=["documents"])


def document_wire(doc: Document) -> dict[str, Any]:
    """ORM 行 → 契约消息 → 线格式(camelCase;只出契约字段)。"""
    data: dict[str, Any] = {
        "id": doc.id,
        "filename": doc.filename,
        "mimeType": doc.mime_type,
        "sizeBytes": doc.size_bytes,
        "status": doc.status,
        "chunkCount": doc.chunk_count,
        "createdAt": isoformat_ms(doc.created_at),
        "updatedAt": isoformat_ms(doc.updated_at),
    }
    if doc.error_msg is not None:
        data["errorMsg"] = doc.error_msg
    return wire(AgentDocument.from_dict(data))


def _service(ctx: CtxDep, producer: ProducerDep) -> DocumentsService:
    return DocumentsService(
        session_factory=ctx.session_factory,
        vector=ctx.vector,
        run_engine=ctx.run_engine,
        producer=producer,
        settings=ctx.settings,
    )


@router.post("/documents", status_code=201)
async def upload(
    user_id: CurrentUserId,
    ctx: CtxDep,
    producer: ProducerDep,
    file: Annotated[UploadFile, File()],
) -> JSONResponse:
    """上传文档,异步摄取;返回 documentId 与 runId 供订阅进度。"""
    data = await file.read()
    document_id, run_id = await _service(ctx, producer).upload(
        user_id=user_id,
        filename=file.filename or "未命名",
        mime_type=file.content_type or "application/octet-stream",
        data=data,
    )
    return JSONResponse(
        status_code=201,
        content=wire(UploadDocResp(document_id=document_id, run_id=run_id)),
    )


@router.get("/documents")
async def list_documents(
    user_id: CurrentUserId, ctx: CtxDep, producer: ProducerDep
) -> JSONResponse:
    docs = await _service(ctx, producer).list(user_id)
    return JSONResponse(content=[document_wire(d) for d in docs])


@router.get("/documents/{document_id}")
async def get_document(
    document_id: int, user_id: CurrentUserId, ctx: CtxDep, producer: ProducerDep
) -> JSONResponse:
    doc = await _service(ctx, producer).get(user_id, document_id)
    return JSONResponse(content=document_wire(doc))


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: int, user_id: CurrentUserId, ctx: CtxDep, producer: ProducerDep
) -> Response:
    await _service(ctx, producer).delete(user_id, document_id)
    return Response(status_code=204)
