"""Morning-after wrap-up (01 §10.2, 04 §8): follow-up drafts at 09:00 local the day
after the event ends. Drafts are suggestions the user approves and sends themself."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, select

from app.core import clock, jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.connections.models import Connection
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.profiles import public as profiles

log = structlog.get_logger()
BATCH = 100
LOOKBACK = timedelta(days=4)


def wrapup_at(ends_at: datetime, tz: str) -> datetime:
    local_end = ends_at.astimezone(ZoneInfo(tz))
    return datetime.combine(local_end.date() + timedelta(days=1), time(9), local_end.tzinfo)


@jobs.cron("connections.wrapup_sweep", minute={0, 15, 30, 45})
async def wrapup_sweep() -> None:
    now = clock.now()
    async with UnitOfWork() as session:
        ended = await events.events_with_status(session, "ended")
    for e in ended:
        if e.ends_at < now - LOOKBACK or wrapup_at(e.ends_at, e.timezone) > now:
            continue
        await jobs.enqueue("connections.wrapup", e.id, job_id=f"wrapup:{e.id}")


@jobs.job("connections.wrapup", timeout_s=300)
async def wrapup(event_id: str) -> None:
    """Idempotent: only rows with no `followup_generated_at` are touched. If the AI is
    down the rows stay untouched and the next sweep retries (06 §1: skip, retry)."""
    async with UnitOfWork() as session:
        event = await events.get_info(session, event_id)
        rows = list(
            (
                await session.execute(
                    select(Connection)
                    .where(
                        Connection.event_id == event_id,
                        Connection.followup_generated_at.is_(None),
                    )
                    .order_by(Connection.user_id, Connection.id)
                    .limit(BATCH)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        if not rows:
            return
        ids = list({c.user_id for c in rows} | {c.peer_id for c in rows})
        cards = await profiles.get_event_cards(session, event_id, ids)
        users = await identity.get_cards(session, ids)
        touched: set[str] = set()
        for c in rows:
            me, peer = users[c.user_id], users[c.peer_id]
            drafts: list[str] = []
            if me.active and peer.active:
                prompt = (
                    f"EVENT: {event.name}\n"
                    f"Met in person: {'yes' if c.met_confirmed_at else 'no, chatted in the app'}\n"
                    f"Sender: {ai.user_data('sender', _line(cards[c.user_id]))}\n"
                    f"Recipient: {ai.user_data('recipient', _line(cards[c.peer_id]))}\n"
                    f"Sender's private notes: {ai.user_data('notes', c.notes)}"
                )
                try:
                    result = await ai.run_task(
                        "followup_drafts", prompt, user_id=c.user_id, event_id=event_id
                    )
                except ai.AiUnavailable:
                    log.warning("wrapup_ai_unavailable", event_id=event_id)
                    break
                options = ai.parsed(result, ai.schemas.Options).options[:2]
                drafts = [
                    ai.validators.clamp(o, 300)
                    for o in options
                    if o.strip() and not ai.validators.contains_contact_details(o)
                ]
            c.followup_drafts = drafts
            c.followup_generated_at = clock.now()
            touched.add(c.user_id)
        await session.flush()
        left = dict(
            (
                await session.execute(
                    select(Connection.user_id, func.count())
                    .where(
                        Connection.event_id == event_id,
                        Connection.followup_generated_at.is_(None),
                        Connection.user_id.in_(touched),
                    )
                    .group_by(Connection.user_id)
                )
            ).all()
        )
        for user_id in sorted(touched):
            if not left.get(user_id):
                outbox.emit(
                    session,
                    "connections.wrapup_ready",
                    {"event_id": event_id, "user_id": user_id, "event_name": event.name},
                )
        more = len(rows) == BATCH
    if more:
        await jobs.enqueue("connections.wrapup", event_id)


def _line(card: profiles.EventCardOut) -> str:
    return ". ".join(x for x in (card.display_name, card.headline, card.offer_text) if x)
