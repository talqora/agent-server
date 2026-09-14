"""rag-server ORM 模型(PostgreSQL,schema=rag)。

与 Node 版 Prisma 表逐一对齐(apps/node-server/prisma/schema.prisma):
users / documents / document_chunks / conversations / messages / task_sessions / runs / run_events。

差异说明(全新库,不背历史):时间列统一用 timestamptz(Prisma 默认 timestamp(3) 无时区)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.db import Base
from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

SCHEMA = "rag"


# ============ 用户 ============
class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "subject", name="uq_users_issuer_subject"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(128))
    role_code: Mapped[str] = mapped_column(String(32))
    # 联合身份(our-chat IdP):按 (issuer, subject) 映射本地自增主键;本地用户两列为 NULL
    issuer: Mapped[str | None] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ============ 文档(用户上传的资料)============
class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_created", "user_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(128))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(512))
    # queued(已上传) → processing(摄取中) → ready | failed
    status: Mapped[str] = mapped_column(String(32))
    error_msg: Mapped[str | None] = mapped_column(Text)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ============ 文档分片(向量存 Milvus,这里存元数据)============
class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_document_index"),
        Index("ix_chunks_user", "user_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.documents.id", ondelete="CASCADE")
    )
    user_id: Mapped[int] = mapped_column(Integer)  # 冗余:便于按用户过滤
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    # 向量库主键(摄取生成的 UUID),Milvus 的 VarChar 主键与此一一对应
    vector_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ============ 会话与消息 ============
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_user_created", "user_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    # [{ chunkId, documentId, score }] — 该回答引用了哪些 chunk
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


# ============ 任务会话(归组多次 agent 任务运行,对齐 Conversation)============
class TaskSession(Base):
    __tablename__ = "task_sessions"
    __table_args__ = (
        Index("ix_task_sessions_user_updated", "user_id", "updated_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[list[Run]] = relationship(
        back_populates="task_session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Run.created_at",
    )


# ============ 运行(泛化:摄取作业 + agent 任务共用)============
class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_user_created", "user_id", "created_at"),
        Index("ix_runs_task_session", "task_session_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # ingestion / agent_task
    ref_id: Mapped[str | None] = mapped_column(String(64))  # 关联 documentId 等
    task_session_id: Mapped[int | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.task_sessions.id", ondelete="CASCADE")
    )
    task: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))  # queued/running/completed/failed
    progress_msg: Mapped[str | None] = mapped_column(String(255))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    task_session: Mapped[TaskSession | None] = relationship(back_populates="runs")
    events: Mapped[list[RunEvent]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RunEvent.sequence_no",
    )


# ============ 运行事件(事件溯源)============
class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_no", name="uq_run_events_sequence"),
        Index("ix_run_events_run", "run_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.runs.run_id", ondelete="CASCADE"))
    sequence_no: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[Run] = relationship(back_populates="events")
