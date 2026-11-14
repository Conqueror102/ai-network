"""Async engine and session factory."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings

_engine: AsyncEngine | None = None
_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        timeout = s.db_statement_timeout_ms * (12 if s.role in ("worker", "scheduler") else 1)
        connect_args: dict[str, Any] = {"server_settings": {"statement_timeout": str(timeout)}}
        if s.database_pooled:
            # PgBouncer transaction mode: no prepared statement cache
            connect_args["statement_cache_size"] = 0
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=5,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _factory
    if _factory is None:
        _factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _factory


def set_session_factory(factory: async_sessionmaker[AsyncSession] | None) -> None:
    """Test hook: bind sessions to a rolled-back outer transaction."""
    global _factory
    _factory = factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session (one transaction) per request.

    Services call `await session.commit()` through their unit of work; anything
    uncommitted is rolled back when the request ends.
    """
    async with get_session_factory()() as session:
        try:
            yield session
        finally:
            await session.rollback()


DbSession = Annotated[AsyncSession, Depends(get_session)]


async def dispose_engine() -> None:
    global _engine, _factory
    if _engine is not None:
        await _engine.dispose()
    _engine, _factory = None, None
