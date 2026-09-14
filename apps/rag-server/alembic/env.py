"""Alembic 环境:异步引擎 + rag schema。

- 连接串来自 DATABASE_URL(与运行时同一配置源,避免两处漂移);
- 版本表 alembic_version 放在 rag schema;
- schema 的创建用**独立连接 + begin() 显式提交**完成——若混进迁移事务,
  连接关闭时的隐式回滚会把整批 DDL 一起回滚(踩过)。
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from agent_core.db import Base
from alembic import context
from rag_server.db import models  # noqa: F401  导入即注册全部模型到 Base.metadata
from rag_server.db.models import SCHEMA
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config, create_async_engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        # 回退到统一配置源(pydantic-settings 读 apps/rag-server/.env),避免两处配置漂移
        from rag_server.settings import get_settings

        url = get_settings().database_url
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _ensure_schema(url: str) -> None:
    """确保 rag schema 存在(版本表要落在其中)。独立连接 + 显式提交。"""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"'))
    await engine.dispose()


async def run_async_migrations() -> None:
    url = _database_url()
    await _ensure_schema(url)
    connectable = async_engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
