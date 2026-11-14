"""Events: lifecycle, registration, rotating-QR check-in, live stats, announcements."""

from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, outbox, ratelimit
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import NotFound, RateLimited
from app.core.ids import new_id
from app.core.observability import CHECKINS
from app.core.security.hashing import random_token
from app.modules.ai import public as ai
from app.modules.events import errors, qr
from app.modules.events.models import Announcement, Checkin, Event, EventApplication
from app.modules.events.schemas import (
    AnnouncementOut,
    ApplicationOut,
    EventCreateIn,
    EventOut,
    EventPatchIn,
    LiveStatsOut,
)
from app.modules.identity import public as identity

CHECKIN_OPENS_BEFORE = timedelta(hours=2)
_TRANSITIONS = {
    "draft": {"published", "cancelled"},
    "published": {"live", "cancelled", "ended"},
    "live": {"ended", "cancelled"},
    "ended": set(),
    "cancelled": set(),
}


def to_out(
    event: Event, *, show_address: bool, application: str | None = None, checked_in: bool = False
) -> EventOut:
    return EventOut(
        id=event.id,
        organizer_id=event.organizer_id,
        name=event.name,
        description=event.description,
        cover_url=event.cover_url,
        venue_name=event.venue_name,
        city_code=event.city_code,
        address=event.address if show_address else None,
        timezone=event.timezone,
        starts_at=event.starts_at,
        ends_at=event.ends_at,
        capacity=event.capacity,
        gating=event.gating,
        visibility=event.visibility,
        status=event.status,
        meeting_points=event.meeting_points,
        my_application=application,
        checked_in=checked_in,
    )


async def get_event(session: AsyncSession, event_id: str) -> Event:
    event = await session.get(Event, event_id)
    if event is None:
        raise NotFound
    return event


# --- organizer side --------------------------------------------------------------------


async def create(session: AsyncSession, organizer_id: str, data: EventCreateIn) -> Event:
    event = Event(
        id=new_id("evt"),
        organizer_id=organizer_id,
        door_qr_seed=random_token(32),
        status="draft",
        static_door_qr_enabled=False,
        **data.model_dump(),
    )
    session.add(event)
    await session.commit()
    return event


async def update(session: AsyncSession, event: Event, patch: EventPatchIn) -> Event:
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(event, field, value)
    if event.ends_at <= event.starts_at:
        from app.core.errors import ValidationFailed

        raise ValidationFailed("ends_at must be after starts_at")
    await session.commit()
    return event


async def set_status(session: AsyncSession, event: Event, status: str) -> Event:
    if status not in _TRANSITIONS[event.status]:
        raise errors.InvalidTransition(details={"from": event.status, "to": status})
    event.status = status
    outbox.emit(session, f"events.event_{status}", {"event_id": event.id})
    await session.commit()
    return event


async def list_for_organizer(
    session: AsyncSession, organizer_id: str, cursor: str | None, limit: int
) -> tuple[list[Event], str | None]:
    q = select(Event).where(Event.organizer_id == organizer_id)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Event.id < after)
    rows = list((await session.execute(q.order_by(Event.id.desc()).limit(limit + 1))).scalars())
    return paginate(rows, limit, lambda e: e.id)


async def list_applications(
    session: AsyncSession, event_id: str, status: str | None, cursor: str | None, limit: int
) -> tuple[list[ApplicationOut], str | None]:
    q = select(EventApplication).where(EventApplication.event_id == event_id)
    if status:
        q = q.where(EventApplication.status == status)
    after = decode_cursor(cursor)
    if after:
        q = q.where(EventApplication.id > after)
    rows = list((await session.execute(q.order_by(EventApplication.id).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda a: a.id)
    cards = await identity.get_cards(session, [a.user_id for a in rows])
    return [
        ApplicationOut(
            id=a.id,
            user_id=a.user_id,
            display_name=cards[a.user_id].display_name,
            headline=cards[a.user_id].headline,
            status=a.status,
            created_at=a.created_at,
        )
        for a in rows
    ], nxt


async def decide_application(
    session: AsyncSession, application_id: str, event_id: str, approve: bool, decided_by: str
) -> EventApplication:
    app = await session.get(EventApplication, application_id)
    if app is None or app.event_id != event_id:
        raise NotFound
    app.status = "approved" if approve else "rejected"
    app.decided_by, app.decided_at = decided_by, clock.now()
    outbox.emit(
        session,
        "events.application_decided",
        {"event_id": event_id, "user_id": app.user_id, "status": app.status},
    )
    await session.commit()
    return app


def door_qr(event: Event) -> tuple[str, int, str | None]:
    static = qr.static_token(event.door_qr_seed, event.id) if event.static_door_qr_enabled else None
    return qr.rotating_token(event.door_qr_seed, event.id), qr.seconds_left(), static


async def live_stats(session: AsyncSession, event: Event) -> LiveStatsOut:
    total = (
        await session.execute(
            select(func.count(func.distinct(Checkin.user_id))).where(Checkin.event_id == event.id)
        )
    ).scalar_one()
    now = clock.now()
    since = now - timedelta(hours=1)
    times = (
        await session.execute(
            select(Checkin.scanned_at).where(
                Checkin.event_id == event.id, Checkin.scanned_at >= since
            )
        )
    ).scalars()
    buckets = [0] * 12
    for t in times:
        idx = min(11, int((t - since).total_seconds() // 300))
        buckets[idx] += 1
    return LiveStatsOut(checked_in=total, capacity=event.capacity, checkins_last_hour=buckets)


async def announce(session: AsyncSession, event: Event, author_id: str, body: str) -> Announcement:
    try:
        await ratelimit.hit("announce", event.id, limit=1, window_s=600)
    except RateLimited as e:
        raise errors.AnnouncementRateLimited(
            retry_after_s=e.details.get("retry_after_s", 600)
        ) from e
    try:
        verdict = await ai.screen(body, kind="announcement", user_id=author_id, event_id=event.id)
    except ai.AiUnavailable:
        verdict = None  # organizers are accountable members; do not block ops on AI
    if verdict is not None and not verdict.allow and verdict.category != "pii_leak":
        raise errors.ContentRejected(details={"category": verdict.category})
    ann = Announcement(id=new_id("ann"), event_id=event.id, author_id=author_id, body=body)
    session.add(ann)
    await session.flush()
    outbox.emit(
        session,
        "events.announcement_created",
        {
            "event_id": event.id,
            "announcement_id": ann.id,
            "body": body,
            "event_name": event.name,
            "created_at": ann.created_at.isoformat(),
        },
    )
    await session.commit()
    return ann


# --- attendee side ---------------------------------------------------------------------


async def discover(
    session: AsyncSession, *, city: str | None, q: str | None, cursor: str | None, limit: int
) -> tuple[list[Event], str | None]:
    query = select(Event).where(
        Event.visibility == "public", Event.status.in_(("published", "live"))
    )
    if city:
        query = query.where(Event.city_code == city)
    if q:
        query = query.where(Event.name.ilike(f"%{q.replace('%', '').replace('_', '')}%"))
    after = decode_cursor(cursor)
    if after:
        ts, eid = clock.now().fromisoformat(after[0]), after[1]
        query = query.where(or_(Event.starts_at > ts, and_(Event.starts_at == ts, Event.id > eid)))
    rows = list(
        (
            await session.execute(query.order_by(Event.starts_at, Event.id).limit(limit + 1))
        ).scalars()
    )
    return paginate(rows, limit, lambda e: [e.starts_at.isoformat(), e.id])


async def application_status(session: AsyncSession, event_id: str, user_id: str) -> str | None:
    return (
        await session.execute(
            select(EventApplication.status).where(
                EventApplication.event_id == event_id, EventApplication.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def is_checked_in(session: AsyncSession, event_id: str, user_id: str) -> bool:
    return (
        await session.execute(
            select(Checkin.id)
            .where(Checkin.event_id == event_id, Checkin.user_id == user_id)
            .limit(1)
        )
    ).scalar_one_or_none() is not None


def visible_to_attendees(event: Event) -> bool:
    return event.status in ("published", "live", "ended")


async def apply(session: AsyncSession, event: Event, user_id: str) -> str:
    if event.status not in ("published", "live"):
        raise NotFound
    status = "approved" if event.gating == "open" else "pending"
    stmt = (
        pg_insert(EventApplication)
        .values(
            id=new_id("app"),
            event_id=event.id,
            user_id=user_id,
            status=status,
            decided_at=clock.now() if status == "approved" else None,
        )
        .on_conflict_do_nothing(index_elements=["event_id", "user_id"])
    )
    await session.execute(stmt)
    await session.commit()
    return await application_status(session, event.id, user_id) or status


async def check_in(session: AsyncSession, event: Event, user_id: str, token: str) -> None:
    now = clock.now()
    if event.status not in ("published", "live") or not (
        event.starts_at - CHECKIN_OPENS_BEFORE <= now <= event.ends_at
    ):
        raise errors.EventNotLive
    verdict = qr.check(
        token,
        seed=event.door_qr_seed,
        event_id=event.id,
        static_enabled=event.static_door_qr_enabled,
    )
    if verdict == "stale":
        raise errors.QrStale
    if verdict != "ok":
        raise errors.QrInvalid
    status = await application_status(session, event.id, user_id)
    if status is None and event.gating == "open":
        status = await apply(session, event, user_id)
    if status != "approved":
        raise errors.CheckinNotApproved
    first_ever = not await is_checked_in(session, event.id, user_id)
    if first_ever and event.capacity is not None:
        count = (
            await session.execute(
                select(func.count(func.distinct(Checkin.user_id))).where(
                    Checkin.event_id == event.id
                )
            )
        ).scalar_one()
        if count >= event.capacity:
            raise errors.EventFull
    result = await session.execute(
        pg_insert(Checkin)
        .values(
            id=new_id("chk"), event_id=event.id, user_id=user_id, day=now.date(), scanned_at=now
        )
        .on_conflict_do_nothing(index_elements=["event_id", "user_id", "day"])
    )
    if event.status == "published":
        event.status = "live"
    if result.rowcount:  # type: ignore[attr-defined]
        CHECKINS.inc()
        outbox.emit(
            session,
            "events.checked_in",
            {"event_id": event.id, "user_id": user_id, "first": first_ever},
        )
    await session.commit()


async def list_announcements(
    session: AsyncSession, event_id: str, cursor: str | None, limit: int
) -> tuple[list[AnnouncementOut], str | None]:
    q = select(Announcement).where(Announcement.event_id == event_id)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Announcement.id < after)
    rows = list(
        (await session.execute(q.order_by(Announcement.id.desc()).limit(limit + 1))).scalars()
    )
    rows, nxt = paginate(rows, limit, lambda a: a.id)
    return [
        AnnouncementOut(id=a.id, event_id=a.event_id, body=a.body, created_at=a.created_at)
        for a in rows
    ], nxt
