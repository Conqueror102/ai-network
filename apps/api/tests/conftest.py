import os

os.environ.setdefault("ENV", "test")
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://postgres@localhost:5432/ainet_test"
)
os.environ["REDIS_URL"] = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/15")

import subprocess
import sys

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import clock, flags, jobs
from app.core.config import get_settings
from app.core.db import engine as db_engine
from app.core.redis import close_redis, get_redis


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    """Build the schema with the real migrations so they are tested on every run."""
    env = {**os.environ, "DATABASE_URL_DIRECT": os.environ["DATABASE_URL"]}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=True, env=env)


@pytest.fixture(scope="session")
async def _engine(_migrate):
    eng = create_async_engine(get_settings().database_url)
    yield eng
    await eng.dispose()


@pytest.fixture(autouse=True)
async def _isolation(_engine):
    """Each test runs inside one outer transaction that is rolled back."""
    async with _engine.connect() as conn:
        trans = await conn.begin()
        db_engine.set_session_factory(
            async_sessionmaker(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )
        )
        await close_redis()
        await get_redis().flushdb()
        jobs.clear_pending()
        flags.clear_cache()
        clock.reset()
        yield
        db_engine.set_session_factory(None)
        await trans.rollback()
    await close_redis()


@pytest.fixture
async def session(_isolation):
    async with db_engine.get_session_factory()() as s:
        yield s


@pytest.fixture(scope="session")
def app():
    from app.bootstrap import create_app

    return create_app("api")


@pytest.fixture
async def client(app, _isolation):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
