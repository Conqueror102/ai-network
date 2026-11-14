"""Background job registry and enqueue helper over ARQ (doc 11 §7.4).

Jobs are thin: `@job("matching.compute_for_user")` functions call a service.
In `ENV=test` jobs are queued in memory and run with `run_pending()`, so tests
exercise the same code path without a worker.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import structlog
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

log = structlog.get_logger()

JobFn = Callable[..., Awaitable[Any]]


@dataclass
class JobSpec:
    name: str
    fn: JobFn
    timeout_s: int = 60
    max_tries: int = 3


@dataclass
class CronSpec:
    name: str
    fn: JobFn
    minute: set[int] | None = None
    hour: set[int] | None = None
    second: set[int] = field(default_factory=lambda: {0})


REGISTRY: dict[str, JobSpec] = {}
CRONS: list[CronSpec] = []
_pool: ArqRedis | None = None
_memory_queue: list[tuple[str, tuple[Any, ...], str | None]] = []


def job(name: str, *, timeout_s: int = 60, max_tries: int = 3) -> Callable[[JobFn], JobFn]:
    def deco(fn: JobFn) -> JobFn:
        REGISTRY[name] = JobSpec(name, fn, timeout_s, max_tries)
        return fn

    return deco


def cron(
    name: str, *, minute: set[int] | None = None, hour: set[int] | None = None
) -> Callable[[JobFn], JobFn]:
    def deco(fn: JobFn) -> JobFn:
        CRONS.append(CronSpec(name, fn, minute, hour))
        return fn

    return deco


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def enqueue(
    name: str, *args: Any, job_id: str | None = None, defer_s: float | None = None
) -> None:
    """Enqueue a registered job. `job_id` dedupes (and with defer_s, debounces)."""
    if name not in REGISTRY:
        raise KeyError(f"unknown job: {name}")
    if get_settings().env == "test":
        if job_id and any(j[2] == job_id for j in _memory_queue):
            return
        _memory_queue.append((name, args, job_id))
        return
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    await _pool.enqueue_job(
        name, *args, _job_id=job_id, _defer_by=timedelta(seconds=defer_s) if defer_s else None
    )


async def run_pending(max_rounds: int = 20) -> int:
    """Test helper: run queued in-memory jobs (jobs may enqueue more)."""
    ran = 0
    for _ in range(max_rounds):
        if not _memory_queue:
            break
        batch = list(_memory_queue)
        _memory_queue.clear()
        for name, args, _ in batch:
            await REGISTRY[name].fn(*args)
            ran += 1
    return ran


def pending() -> list[tuple[str, tuple[Any, ...], str | None]]:
    return list(_memory_queue)


def clear_pending() -> None:
    _memory_queue.clear()
