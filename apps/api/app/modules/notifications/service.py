"""`notify()`: in-app inbox, then live WebSocket, then push (07 §3).

Quiet hours (22:00 to 08:00 local) hold non-urgent pushes until morning; the inbox row
and the live event are never held. A muted category still lands in the inbox.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, jobs
from app.core.db.pagination import decode_cursor, paginate
from app.core.ids import new_id
from app.modules.notifications.models import Notification, NotificationPref
from app.modules.notifications.schemas import CATEGORIES
from app.modules.realtime import public as realtime

DEFAULT_TZ = "Africa/Lagos"
QUIET_START, QUIET_END = 22, 8
PUSH_ALWAYS = {"wave", "wave_accepted", "meet", "event", "wrapup", "safety"}
URGENT = {"meet"}  # exempt from quiet hours


def quiet_delay_s(now: datetime, tz: str) -> float:
    """Seconds until 08:00 local if `now` is inside quiet hours, else 0."""
    local = now.astimezone(ZoneInfo(tz))
    if QUIET_END <= local.hour < QUIET_START:
        return 0.0
    wake = local.replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
    if local.hour >= QUIET_START:
        wake += timedelta(days=1)
    return (wake - local).total_seconds()


async def push_enabled(session: AsyncSession, user_id: str, category: str) -> bool:
    row = await session.get(NotificationPref, (user_id, category))
    return True if row is None else row.push_enabled


async def notify(
    session: AsyncSession,
    user_id: str,
    category: str,
    title: str,
    body: str,
    *,
    data: dict[str, Any] | None = None,
    collapse: str | None = None,
    tz: str = DEFAULT_TZ,
    store: bool = True,
    message_id: str | None = None,
) -> None:
    """`message_id`: for chat pushes the preview text is resolved when the push is sent,
    so message text never sits in the job queue."""
    data = data or {}
    if store:
        row = Notification(
            id=new_id("ntf"), user_id=user_id, category=category, title=title, body=body, data=data
        )
        session.add(row)
        await session.flush()
        await realtime.publish_user(
            user_id,
            "notification.new",
            {"id": row.id, "category": category, "title": title, "body": body, "data": data},
        )
    if not await push_enabled(session, user_id, category):
        return
    if category not in PUSH_ALWAYS and await realtime.is_online(user_id):
        return  # they are looking at the app; the socket already told them
    delay = 0.0 if category in URGENT else quiet_delay_s(clock.now(), tz)
    await jobs.enqueue(
        "notifications.push",
        user_id,
        {
            "category": category,
            "title": title,
            "body": body,
            "data": data,
            "collapse": collapse,
            "message_id": message_id,
        },
        defer_s=delay or None,
    )


# --- inbox -----------------------------------------------------------------------------


async def list_inbox(
    session: AsyncSession, me: str, cursor: str | None, limit: int
) -> tuple[list[Notification], str | None]:
    q = select(Notification).where(Notification.user_id == me)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Notification.id < str(after))
    rows = list(
        (await session.execute(q.order_by(Notification.id.desc()).limit(limit + 1))).scalars()
    )
    return paginate(rows, limit, lambda n: n.id)


async def unread_count(session: AsyncSession, me: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.user_id == me, Notification.read_at.is_(None))
            )
        ).scalar_one()
    )


async def mark_read(session: AsyncSession, me: str, ids: list[str], everything: bool) -> None:
    q = update(Notification).where(Notification.user_id == me, Notification.read_at.is_(None))
    if not everything:
        if not ids:
            return
        q = q.where(Notification.id.in_(ids))
    await session.execute(q.values(read_at=clock.now()))
    await session.commit()


async def get_prefs(session: AsyncSession, me: str) -> dict[str, bool]:
    rows = dict(
        (
            await session.execute(
                select(NotificationPref.category, NotificationPref.push_enabled).where(
                    NotificationPref.user_id == me
                )
            )
        ).all()
    )
    return {c: rows.get(c, True) for c in CATEGORIES}


async def set_prefs(session: AsyncSession, me: str, push: dict[str, bool]) -> dict[str, bool]:
    for category, enabled in push.items():
        stmt = insert(NotificationPref).values(user_id=me, category=category, push_enabled=enabled)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=["user_id", "category"], set_={"push_enabled": enabled}
            )
        )
    await session.commit()
    return await get_prefs(session, me)
