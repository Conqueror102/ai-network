"""Events' public surface for other modules."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.modules.events.deps import CheckedIn, EventCtx, OrgOwner, OrgStaff
from app.modules.events.models import Checkin, Event
from app.modules.events.service import is_checked_in, list_spots, spot_code


@dataclass(frozen=True)
class EventInfo:
    id: str
    organizer_id: str
    name: str
    venue_name: str
    timezone: str
    starts_at: datetime
    ends_at: datetime
    status: str
    meeting_points: list[str]


def _info(e: Event) -> EventInfo:
    return EventInfo(
        e.id,
        e.organizer_id,
        e.name,
        e.venue_name,
        e.timezone,
        e.starts_at,
        e.ends_at,
        e.status,
        e.meeting_points,
    )


async def get_info(session: AsyncSession, event_id: str) -> EventInfo:
    event = await session.get(Event, event_id)
    if event is None:
        raise NotFound
    return _info(event)


@dataclass(frozen=True)
class SpotInfo:
    id: str
    number: int
    code: str
    label: str
    hint: str | None

    @property
    def place(self) -> str:
        """What people say and what the sign shows: "M3 · Coffee stand"."""
        return f"{self.code} · {self.label}"


async def active_spots(session: AsyncSession, event_id: str) -> list[SpotInfo]:
    return [
        SpotInfo(s.id, s.number, spot_code(s.number), s.label, s.hint)
        for s in await list_spots(session, event_id, active_only=True)
    ]


async def get_infos(session: AsyncSession, event_ids: list[str]) -> dict[str, EventInfo]:
    if not event_ids:
        return {}
    rows = (await session.execute(select(Event).where(Event.id.in_(set(event_ids))))).scalars()
    return {e.id: _info(e) for e in rows}


async def live_event_ids(session: AsyncSession) -> list[str]:
    return list((await session.execute(select(Event.id).where(Event.status == "live"))).scalars())


async def events_with_status(session: AsyncSession, status: str) -> list[EventInfo]:
    rows = (await session.execute(select(Event).where(Event.status == status))).scalars()
    return [_info(e) for e in rows]


async def checked_in_user_ids(session: AsyncSession, event_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(Checkin.user_id).where(Checkin.event_id == event_id).distinct()
            )
        ).scalars()
    )


async def checked_in_count(session: AsyncSession, event_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count(func.distinct(Checkin.user_id))).where(
                    Checkin.event_id == event_id
                )
            )
        ).scalar_one()
    )


async def live_checked_in_event_ids(session: AsyncSession, user_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(Event.id)
                .join(Checkin, Checkin.event_id == Event.id)
                .where(Checkin.user_id == user_id, Event.status == "live")
                .distinct()
            )
        ).scalars()
    )


async def checked_in_today(session: AsyncSession, event_id: str, user_ids: list[str]) -> set[str]:
    if not user_ids:
        return set()
    from app.core import clock

    return set(
        (
            await session.execute(
                select(Checkin.user_id).where(
                    Checkin.event_id == event_id,
                    Checkin.user_id.in_(user_ids),
                    Checkin.day == clock.now().date(),
                )
            )
        ).scalars()
    )


def checked_in_subquery(event_id: str):  # type: ignore[no-untyped-def]
    """`user_id IN (...)` filter for people queries scoped to an event."""
    return select(Checkin.user_id).where(Checkin.event_id == event_id)


__all__ = [
    "CheckedIn",
    "EventCtx",
    "EventInfo",
    "OrgOwner",
    "OrgStaff",
    "SpotInfo",
    "active_spots",
    "checked_in_count",
    "checked_in_subquery",
    "checked_in_today",
    "checked_in_user_ids",
    "events_with_status",
    "get_info",
    "get_infos",
    "is_checked_in",
    "live_checked_in_event_ids",
    "live_event_ids",
]
