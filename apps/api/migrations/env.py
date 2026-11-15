"""Alembic environment. Uses DATABASE_URL_DIRECT (unpooled) when set."""

import asyncio
import os

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.db.base import Base
from app.registry import load_models

load_models()
target_metadata = Base.metadata
URL = os.environ.get("DATABASE_URL_DIRECT") or get_settings().database_url


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=False,
    )
    with context.begin_transaction():
        connection.execute(text("SET lock_timeout = '3s'"))
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(URL, poolclass=pool.NullPool)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())
