"""rag-server 配置:公共项(agent-core BaseServiceSettings)+ 本服务专属项。

命名空间约定(多服务纪律,见 docs/架构设计/01 §6.3):
- PG schema: rag;Milvus collection: rag_knowledge_chunks;
- Pulsar topic: rag-runs;Redis 频道前缀: rag:。
"""

from functools import lru_cache
from pathlib import Path

from agent_core.settings import BaseServiceSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseServiceSettings):
    # .env 固定解析到 apps/rag-server/.env(不随 CWD 漂移;容器里无文件则走环境变量注入)
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 服务标识 / 命名空间 ──
    service_name: str = "rag"
    port: int = 3101

    # ── 文档摄取 ──
    document_max_bytes: int = 10 * 1024 * 1024
    document_storage_dir: str = "./storage/documents"
    chunk_size: int = 800
    chunk_overlap: int = 100
    embed_batch: int = 16

    # ── Milvus(向量库)──
    milvus_address: str = "localhost:19530"
    milvus_token: str = ""
    milvus_collection: str = "rag_knowledge_chunks"
    milvus_vector_size: int = 768

    # ── LLM(OpenAI 兼容端点;本地默认 Ollama,生产千问等)──
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_chat_model: str = "qwen2.5:7b"
    llm_embed_model: str = "nomic-embed-text"
    llm_timeout_seconds: float = 120.0

    # ── 队列(Pulsar)──
    pulsar_topic: str = "rag-runs"
    pulsar_subscription: str = "rag-worker"

    # ── 检索 / 对话 / agent ──
    rag_top_k: int = 6
    history_limit: int = 10
    agent_max_iterations: int = 8


@lru_cache
def get_settings() -> Settings:
    """进程内单例(启动即校验:缺必填项直接抛错,符合"配置即启动断言")。"""
    # database_url 为必填,mypy 静态不可知;运行时由环境变量提供(pydantic-settings)
    return Settings()  # type: ignore[call-arg]
