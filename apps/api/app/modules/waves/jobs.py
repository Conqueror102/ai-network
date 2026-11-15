from datetime import timedelta
from zoneinfo import ZoneInfo

from app.core import clock, jobs
from app.core.db.uow import UnitOfWork
from app.modules.events import public as events
from app.modules.waves import service

EXPIRE_AFTER = timedelta(hours=24)


@jobs.cron("waves.expire", minute={0, 15, 30, 45})
async def expire() -> None:
    """Open waves die quietly a day after the event ends (01 §7.6). No notifications."""
    now = clock.now()
    async with UnitOfWork() as session:
        ended = await events.events_with_status(session, "ended")
        await service.expire(session, [e.id for e in ended if e.ends_at + EXPIRE_AFTER <= now])


@jobs.cron("waves.resurface", minute={0})
async def resurface() -> None:
    """Hourly: at 09:00 event-local time, bring back waves snoozed on an earlier day."""
    now = clock.now()
    async with UnitOfWork() as session:
        for status in ("live", "ended"):
            for e in await events.events_with_status(session, status):
                local = now.astimezone(ZoneInfo(e.timezone))
                if local.hour != 9:
                    continue
                midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
                await service.resurface(session, e.id, midnight)
