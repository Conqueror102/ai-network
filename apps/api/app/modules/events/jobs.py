from sqlalchemy import select

from app.core import clock, jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.events.models import Event


@jobs.cron("events.sync_status", minute=set(range(60)))
async def sync_status() -> None:
    """published -> live at starts_at, live -> ended at ends_at."""
    now = clock.now()
    async with UnitOfWork() as session:
        starting = (
            await session.execute(
                select(Event)
                .where(Event.status == "published", Event.starts_at <= now, Event.ends_at > now)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        for event in starting:
            event.status = "live"
            outbox.emit(session, "events.event_live", {"event_id": event.id})
        ending = (
            await session.execute(
                select(Event)
                .where(Event.status.in_(("published", "live")), Event.ends_at <= now)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
        for event in ending:
            event.status = "ended"
            outbox.emit(session, "events.event_ended", {"event_id": event.id})
