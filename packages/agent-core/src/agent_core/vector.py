"""向量库封装(Milvus):建集合 / 写入 / 检索 / 按文档删除。

纪律(与 Node 版对齐,apps/node-server/src/shared/milvus/milvus.service.ts):
- **search_by_user 是全应用唯一检索出口**,user_id 过滤写死在这一层——从结构上杜绝越权检索;
- 启动 ensure_collection(幂等):建集合 + 向量索引 + load 到 Loaded(检索/删除的前置条件);
- 集合维度必须与 embedding 模型一致;换模型要重建集合,故集合名建议带服务/维度标识。

pymilvus 是同步客户端 → 统一用 asyncio.to_thread 包装,避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from pymilvus import CollectionSchema, DataType, FieldSchema, MilvusClient
from pymilvus.milvus_client.index import IndexParams

logger = logging.getLogger("agent_core.vector")


@dataclass(frozen=True)
class ChunkPoint:
    """写入向量库的一个点:主键 + 向量 + 标量负载(回指 PG 行)。"""

    id: str
    vector: list[float]
    payload: dict[str, int]  # user_id / document_id / chunk_id / chunk_index


@dataclass(frozen=True)
class VectorHit:
    """检索命中:标量负载 + 相似度分。"""

    payload: dict[str, int]
    score: float


class MilvusVectorStore:
    def __init__(
        self,
        *,
        address: str,
        token: str = "",
        collection: str,
        vector_size: int,
        metric_type: str = "COSINE",
    ) -> None:
        # 兼容 Node 版地址写法(host:port):pymilvus MilvusClient 需要 scheme 前缀
        normalized = address if "://" in address else f"http://{address}"
        self._client = MilvusClient(uri=normalized, token=token or None)
        self._collection = collection
        self._vector_size = vector_size
        self._metric = metric_type

    @property
    def collection(self) -> str:
        return self._collection

    async def ensure_collection(self) -> None:
        """幂等:不存在则建集合 + 索引;无论新建与否都确保已 load。"""
        has = await asyncio.to_thread(self._client.has_collection, self._collection)
        if not has:
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64),
                FieldSchema(name="vector", dtype=DataType.FLOAT_VECTOR, dim=self._vector_size),
                FieldSchema(name="user_id", dtype=DataType.INT64),
                FieldSchema(name="document_id", dtype=DataType.INT64),
                FieldSchema(name="chunk_id", dtype=DataType.INT64),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
            ]
            schema = CollectionSchema(fields=fields)
            index_params = IndexParams()
            index_params.add_index(
                field_name="vector", index_type="AUTOINDEX", metric_type=self._metric
            )

            def _create() -> None:
                self._client.create_collection(
                    collection_name=self._collection,
                    schema=schema,
                    index_params=index_params,
                    # Strong:摄取双写(PG + Milvus)后需立即可检索
                    consistency_level="Strong",
                )

            await asyncio.to_thread(_create)
            logger.info("Milvus collection %s 已创建(dim=%s)", self._collection, self._vector_size)
        await self._load()

    async def _load(self) -> None:
        """load 进内存并轮询到 Loaded 再返回(load 是异步过程)。"""

        def _load_sync() -> None:
            self._client.load_collection(self._collection)

        await asyncio.to_thread(_load_sync)
        for _ in range(60):
            state = await asyncio.to_thread(self._client.get_load_state, self._collection)
            value = state.get("state") if isinstance(state, dict) else state
            # LoadState 枚举的 str 形如 "<LoadState.Loaded: 3>"
            if "Loaded" in str(value):
                return
            await asyncio.sleep(0.5)
        raise RuntimeError(f"Milvus collection {self._collection} 载入超时")

    async def upsert_chunks(self, points: list[ChunkPoint]) -> None:
        """批量写入(upsert 按主键幂等;集合 Strong 一致,返回后即可检索)。"""
        if not points:
            return
        data = [
            {
                "id": p.id,
                "vector": p.vector,
                "user_id": p.payload["user_id"],
                "document_id": p.payload["document_id"],
                "chunk_id": p.payload["chunk_id"],
                "chunk_index": p.payload["chunk_index"],
            }
            for p in points
        ]
        await asyncio.to_thread(self._client.upsert, self._collection, data)

    async def search_by_user(
        self, vector: list[float], user_id: int, top_k: int
    ) -> list[VectorHit]:
        """向量检索,强制按 user_id 过滤——多租户隔离的唯一出口。"""

        def _search() -> list[Any]:
            return list(
                self._client.search(
                    collection_name=self._collection,
                    data=[vector],
                    limit=top_k,
                    filter=f"user_id == {user_id}",
                    output_fields=["user_id", "document_id", "chunk_id", "chunk_index"],
                    search_params={"metric_type": self._metric},
                )
            )

        results = await asyncio.to_thread(_search)
        hits: list[VectorHit] = []
        for raw in results[0] if results else []:
            entity = raw.get("entity", {})
            hits.append(
                VectorHit(
                    payload={
                        "user_id": int(entity["user_id"]),
                        "document_id": int(entity["document_id"]),
                        "chunk_id": int(entity["chunk_id"]),
                        "chunk_index": int(entity["chunk_index"]),
                    },
                    score=float(raw.get("distance", 0.0)),
                )
            )
        return hits

    async def delete_by_document(self, document_id: int) -> None:
        """按文档删除全部向量点(摄取重试清场 / 删文档)。"""
        await asyncio.to_thread(
            self._client.delete, self._collection, filter=f"document_id == {document_id}"
        )

    async def ping(self) -> None:
        """健康检查:列集合(会发起一次 gRPC 调用)。"""
        await asyncio.to_thread(self._client.list_collections)
