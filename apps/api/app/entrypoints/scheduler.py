"""ARQ scheduler: cron jobs only. They enqueue work; they never do heavy work."""

from typing import Any

from arq import cron

from app.core import jobs
from app.core.logging import configure_logging
from app.registry import load_handlers, load_models

load_models()
load_handlers()


def _cron(spec: jobs.CronSpec) -> Any:
    async def runner(ctx: dict[str, Any]) -> None:
        await spec.fn()

    runner.__qualname__ = f"cron_{spec.name.replace('.', '_')}"
    return cron(
        runner, name=spec.name, minute=spec.minute, hour=spec.hour, second=spec.second, unique=True
    )


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()


class SchedulerSettings:
    cron_jobs = [_cron(s) for s in jobs.CRONS]
    functions: list[Any] = []
    redis_settings = jobs.redis_settings()
    on_startup = startup
    queue_name = "arq:scheduler"
