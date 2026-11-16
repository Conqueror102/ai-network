"""Profiles' public surface: event cards and goal data for matching, waves, chat, ads."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.profiles.models import EventProfile, Goal
from app.modules.profiles.schemas import EventCardOut
from app.modules.safety import public as safety


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
    open_to_all: bool = True


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
            open_to_all=p.open_to_all,
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


def _people(event_id: str, me: str, exclude: set[str]) -> list[Any]:
    """The people `me` may be shown in this event (05 §2 stage 1, minus caller-owned
    exclusions): checked in, not hidden, not blocked either way, not self."""
    conds: list[Any] = [
        EventProfile.event_id == event_id,
        EventProfile.visibility != "hidden",
        EventProfile.user_id != me,
        EventProfile.user_id.in_(events.checked_in_subquery(event_id)),
        safety.not_blocked(me, EventProfile.user_id),
    ]
    if exclude:
        conds.append(EventProfile.user_id.not_in(exclude))
    return conds


async def nearest_offers(
    session: AsyncSession,
    event_id: str,
    me: str,
    vector: list[float],
    *,
    exclude: set[str],
    limit: int = 40,
) -> list[tuple[str, str, float]]:
    """05 §3 candidate generation: the offers and profiles closest to an ask.
    Returns (user_id, "profile" | goal id, cosine similarity), best first."""
    conds = _people(event_id, me, exclude)
    d_profile = EventProfile.profile_embedding.cosine_distance(vector)
    d_goal = Goal.offer_embedding.cosine_distance(vector)
    by_profile = (
        select(EventProfile.user_id, literal("profile"), d_profile)
        .where(*conds, EventProfile.profile_embedding.is_not(None))
        .order_by(d_profile)
        .limit(limit)
    )
    by_goal = (
        select(EventProfile.user_id, Goal.id, d_goal)
        .join(Goal, Goal.event_profile_id == EventProfile.id)
        .where(*conds, Goal.status == "active", Goal.offer_embedding.is_not(None))
        .order_by(d_goal)
        .limit(limit)
    )
    rows = [*(await session.execute(by_profile)).all(), *(await session.execute(by_goal)).all()]
    out = []
    for user_id, source, dist in rows:
        sim = 0.0 if dist is None or dist != dist else 1.0 - float(dist)  # NaN: zero vector
        out.append((str(user_id), str(source), sim))
    return sorted(out, key=lambda r: -r[2])[:limit]


async def showable_ids(
    session: AsyncSession, event_id: str, me: str, user_ids: list[str]
) -> set[str]:
    """Subset of `user_ids` that `me` may see in this event right now."""
    if not user_ids:
        return set()
    conds = _people(event_id, me, set())
    return set(
        (
            await session.execute(
                select(EventProfile.user_id).where(*conds, EventProfile.user_id.in_(user_ids))
            )
        ).scalars()
    )


async def open_ids(session: AsyncSession, event_id: str, user_ids: list[str]) -> set[str]:
    """Subset of `user_ids` who are open to meeting anyone. The rest have asked to be
    reachable only by the people they are matched with."""
    if not user_ids:
        return set()
    return set(
        (
            await session.execute(
                select(EventProfile.user_id).where(
                    EventProfile.event_id == event_id,
                    EventProfile.user_id.in_(user_ids),
                    EventProfile.open_to_all.is_(True),
                )
            )
        ).scalars()
    )


async def profile_count(session: AsyncSession, event_id: str) -> int:
    from sqlalchemy import func

    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(EventProfile)
                .where(EventProfile.event_id == event_id, EventProfile.visibility != "hidden")
            )
        ).scalar_one()
    )


async def user_ids_with_profile(session: AsyncSession, event_id: str) -> list[str]:
    return list(
        (
            await session.execute(
                select(EventProfile.user_id).where(EventProfile.event_id == event_id)
            )
        ).scalars()
    )


async def export_user(session: AsyncSession, user_id: str) -> list[dict[str, Any]]:
    """Every event profile and goal the user wrote. Embeddings are derived data and
    are left out."""
    profiles = (
        await session.scalars(select(EventProfile).where(EventProfile.user_id == user_id))
    ).all()
    out: list[dict[str, Any]] = []
    for p in profiles:
        goals = (
            await session.scalars(
                select(Goal).where(Goal.event_profile_id == p.id).order_by(Goal.priority)
            )
        ).all()
        out.append(
            {
                "event_id": p.event_id,
                "display_name": p.display_name,
                "headline": p.headline,
                "offer_text": p.offer_text,
                "visibility": p.visibility,
                "goals": [
                    {
                        "intent": g.intent,
                        "raw_input": g.raw_input,
                        "offer": g.offer,
                        "priority": g.priority,
                        "status": g.status,
                    }
                    for g in goals
                ],
            }
        )
    return out


__all__ = [
    "EventCardOut",
    "GoalData",
    "ProfileData",
    "export_user",
    "get_event_cards",
    "load_profiles",
    "nearest_offers",
    "open_ids",
    "profile_count",
    "showable_ids",
    "user_ids_with_profile",
    "visibility_of",
]
