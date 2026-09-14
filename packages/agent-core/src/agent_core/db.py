"""异步数据库基座(SQLAlchemy 2.0 async)。

各服务用自己的 ORM 模型(独立 schema),这里只提供引擎/会话工厂/声明基类。
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """ORM 声明基类。服务侧模型继承它(表归属各自 schema,见服务内 models)。"""


def make_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """创建异步引擎。pool_pre_ping 防连接被中间件回收后取到死连接。"""
    return create_async_engine(database_url, echo=echo, pool_pre_ping=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """会话工厂。expire_on_commit=False:commit 后对象仍可读(避免隐式 IO)。"""
    return async_sessionmaker(engine, expire_on_commit=False)
