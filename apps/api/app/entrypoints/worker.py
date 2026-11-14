"""ARQ worker: runs every registered job plus the outbox relay loop."""

import asyncio
import contextlib
from typing import Any

import structlog
from arq.worker import func

from app.core import jobs, outbox
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.observability import JOBS, OUTBOX_LAG, init_sentry
from app.core.redis import get_redis, key
from app.registry import load_handlers, load_models

log = structlog.get_logger()
load_models()
load_handlers()


def _wrap(spec: jobs.JobSpec) -> Any:
    async def runner(ctx: dict[str, Any], *args: Any) -> Any:
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(job_id=ctx.get("job_id"), job=spec.name)
        try:
            result = await spec.fn(*args)
        except Exception:
            JOBS.labels(spec.name, "error").inc()
            log.exception("job_failed")
            raise
        JOBS.labels(spec.name, "ok").inc()
        return result

    return func(runner, name=spec.name, timeout=spec.timeout_s, max_tries=spec.max_tries)


async def _relay_loop() -> None:
    while True:
        try:
            n = await outbox.relay_once()
            OUTBOX_LAG.set(await outbox.lag_seconds())
            await get_redis().set(key("hb", "worker"), "1", ex=60)
        except Exception:
            log.exception("outbox_relay_error")
            n = 0
        await asyncio.sleep(0.05 if n else 0.5)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    init_sentry(get_settings())
    ctx["relay"] = asyncio.create_task(_relay_loop())


async def shutdown(ctx: dict[str, Any]) -> None:
    ctx["relay"].cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await ctx["relay"]


class WorkerSettings:
    functions = [_wrap(s) for s in jobs.REGISTRY.values()]
    redis_settings = jobs.redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 20
