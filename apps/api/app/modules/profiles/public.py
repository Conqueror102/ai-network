"""Profiles' public surface: event cards and goal data for matching, waves, chat, ads."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity import public as identity
from app.modules.profiles.models import EventProfile, Goal
from app.modules.profiles.schemas import EventCardOut


@dataclass(frozen=True)
class GoalData:
    id: str
    intent: str
    target: dict[str, Any]
    offer: str | None
    raw_input: str | None
    priority: int
    ask_embedding: list[float] | None
    offer_embedding: list[float] | None


@dataclass(frozen=True)
class ProfileData:
    """Matching input for one attendee. Internal: embeddings never leave the server."""

    user_id: str
    display_name: str
    headline: str | None
    offer_text: str | None
    visibility: str
    profile_embedding: list[float] | None
    goals: list[GoalData]
    # from the global profile, for target-filter matching
    role_title: str | None
    company: str | None
    industry: str | None
    skills: list[str]
    bio: str | None


async def load_profiles(
    session: AsyncSession, event_id: str, user_ids: list[str] | None = None
) -> dict[str, ProfileData]:
    q = select(EventProfile).where(EventProfile.event_id == event_id)
    if user_ids is not None:
        q = q.where(EventProfile.user_id.in_(user_ids))
    profiles = list((await session.execute(q)).scalars())
    if not profiles:
        return {}
    goals = list(
        (
            await session.execute(
                select(Goal)
                .where(Goal.event_profile_id.in_([p.id for p in profiles]), Goal.status == "active")
                .order_by(Goal.priority)
            )
        ).scalars()
    )
    by_profile: dict[str, list[GoalData]] = {}
    for g in goals:
        by_profile.setdefault(g.event_profile_id, []).append(
            GoalData(
                g.id,
                g.intent,
                g.target,
                g.offer,
                g.raw_input,
                g.priority,
                None if g.ask_embedding is None else [float(x) for x in g.ask_embedding],
                None if g.offer_embedding is None else [float(x) for x in g.offer_embedding],
            )
        )
    users = await identity.get_cards(session, [p.user_id for p in profiles])
    out = {}
    for p in profiles:
        u = users[p.user_id]
        if not u.active:
            continue
        out[p.user_id] = ProfileData(
            p.user_id,
            p.display_name,
            p.headline,
            p.offer_text,
            p.visibility,
            None if p.profile_embedding is None else [float(x) for x in p.profile_embedding],
            by_profile.get(p.id, []),
            u.role_title,
            u.company,
            u.industry,
            u.skills,
            u.bio,
        )
    return out


async def get_event_cards(
    session: AsyncSession, event_id: str, user_ids: list[str]
) -> dict[str, EventCardOut]:
    """Public-safe cards. Users without an event profile fall back to their global card."""
    if not user_ids:
        return {}
    rows = (
        await session.execute(
            select(EventProfile).where(
                EventProfile.event_id == event_id, EventProfile.user_id.in_(set(user_ids))
            )
        )
    ).scalars()
    profiles = {p.user_id: p for p in rows}
    users = await identity.get_cards(session, user_ids)
    out = {}
    for uid, u in users.items():
        p = profiles.get(uid)
        out[uid] = EventCardOut(
            user_id=uid,
            display_name=p.display_name if p and u.active else u.display_name,
            photo_url=u.photo_url,
            headline=(p.headline if p else u.headline) if u.active else None,
            offer_text=p.offer_text if p and u.active else None,
        )
    return out


async def visibility_of(session: AsyncSession, event_id: str, user_id: str) -> str | None:
    return (
        await session.execute(
            select(EventProfile.visibility).where(
                EventProfile.event_id == event_id, EventProfile.user_id == user_id
            )
        )
    ).scalar_one_or_none()


__all__ = [
    "EventCardOut",
    "GoalData",
    "ProfileData",
    "get_event_cards",
    "load_profiles",
    "visibility_of",
]
