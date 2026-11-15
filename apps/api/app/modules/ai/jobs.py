from datetime import timedelta

import structlog
from sqlalchemy import delete

from app.core import clock, jobs
from app.core.db.uow import UnitOfWork
from app.modules.ai.models import AiCall

log = structlog.get_logger()
CALL_KEEP = timedelta(days=90)


@jobs.cron("ai.retention", hour={2}, minute={40})
async def retention() -> None:
    """`ai_calls` rows are kept for 90 days (02 retention)."""
    async with UnitOfWork() as session:
        res = await session.execute(
            delete(AiCall).where(AiCall.created_at < clock.now() - CALL_KEEP)
        )
    log.info("ai_retention", ai_calls=res.rowcount or 0)  # type: ignore[attr-defined]
