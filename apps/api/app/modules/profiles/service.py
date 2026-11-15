"""Event profiles and goals. Edits trigger (debounced) re-embedding, then re-matching."""

from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import jobs
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import NotFound
from app.core.ids import new_id
from app.modules.ai import public as ai
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.profiles import errors
from app.modules.profiles.models import EventProfile, Goal
from app.modules.profiles.schemas import (
    EventCardOut,
    EventProfileIn,
    GoalDraftOut,
    GoalIn,
    GoalOut,
    GoalPatchIn,
    MyEventProfileOut,
    Target,
)
from app.modules.safety import public as safety

EMBED_DEBOUNCE_S = 30
_INTENT_PHRASE = {
    "hire": "I want to hire",
    "get_hired": "I am looking for a job",
    "raise": "I am raising money",
    "invest": "I want to invest",
    "sell": "I want to find customers",
    "buy": "I want to buy",
    "learn": "I want to learn",
    "cofounder": "I am looking for a cofounder",
    "partner": "I am looking for partners",
    "meet": "I want to meet people",
}


async def _screen(text: str, user_id: str, event_id: str) -> None:
    """Reject denied text. If AI is down, accept: profile text is not first contact,
    and the nightly re-screen catches it (wave notes are the fail-closed path)."""
    if not text.strip():
        return
    try:
        verdict = await ai.screen(text, kind="event_profile", user_id=user_id, event_id=event_id)
    except ai.AiUnavailable:
        return
    if not verdict.allow:
        raise errors.ContentRejected(details={"category": verdict.category})


async def _schedule_embed(profile_id: str) -> None:
    await jobs.enqueue(
        "profiles.embed", profile_id, job_id=f"embed:{profile_id}", defer_s=EMBED_DEBOUNCE_S
    )


# --- event profile ---------------------------------------------------------------------


async def get_profile(session: AsyncSession, event_id: str, user_id: str) -> EventProfile | None:
    return (
        await session.execute(
            select(EventProfile).where(
                EventProfile.event_id == event_id, EventProfile.user_id == user_id
            )
        )
    ).scalar_one_or_none()


async def require_profile(session: AsyncSession, event_id: str, user_id: str) -> EventProfile:
    profile = await get_profile(session, event_id, user_id)
    if profile is None:
        raise errors.ProfileRequired
    return profile


async def card_of(session: AsyncSession, profile: EventProfile) -> EventCardOut:
    user = await identity.get_card(session, profile.user_id)
    return EventCardOut(
        user_id=profile.user_id,
        display_name=profile.display_name,
        photo_url=user.photo_url,
        headline=profile.headline,
        offer_text=profile.offer_text,
    )


async def my_profile_out(session: AsyncSession, profile: EventProfile) -> MyEventProfileOut:
    card = await card_of(session, profile)
    return MyEventProfileOut(**card.model_dump(), visibility=profile.visibility)


async def upsert_profile(
    session: AsyncSession, event_id: str, user_id: str, data: EventProfileIn
) -> EventProfile:
    if data.visibility == "radar" and not await identity.has_approved_photo(session, user_id):
        raise errors.RadarRequiresPhoto
    await _screen(
        " \n ".join(filter(None, [data.display_name, data.headline, data.offer_text])),
        user_id,
        event_id,
    )
    profile = await get_profile(session, event_id, user_id)
    if profile is None:
        profile = EventProfile(
            id=new_id("epf"), event_id=event_id, user_id=user_id, **data.model_dump()
        )
        session.add(profile)
    else:
        for field, value in data.model_dump().items():
            setattr(profile, field, value)
    await session.commit()
    await _schedule_embed(profile.id)
    return profile


async def view_profile(session: AsyncSession, event_id: str, me: str, user_id: str) -> EventCardOut:
    """Hidden and blocked are indistinguishable from "does not exist"."""
    profile = await get_profile(session, event_id, user_id)
    if (
        profile is None
        or (profile.visibility == "hidden" and user_id != me)
        or await safety.is_blocked_pair(session, me, user_id)
        or not await events.is_checked_in(session, event_id, user_id)
    ):
        raise errors.NotVisible
    card = await identity.get_card(session, user_id)
    if not card.active:
        raise errors.NotVisible
    return await card_of(session, profile)


async def directory(
    session: AsyncSession, event_id: str, me: str, q: str | None, cursor: str | None, limit: int
) -> tuple[list[EventCardOut], str | None]:
    mine = await require_profile(session, event_id, me)
    if mine.visibility == "hidden":
        raise errors.DirectoryRequiresVisibility  # reciprocity (01 §4)
    query = select(EventProfile).where(
        EventProfile.event_id == event_id,
        EventProfile.visibility != "hidden",
        EventProfile.user_id != me,
        EventProfile.user_id.in_(events.checked_in_subquery(event_id)),
        safety.not_blocked(me, EventProfile.user_id),
    )
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        query = query.where(
            or_(EventProfile.display_name.ilike(like), EventProfile.headline.ilike(like))
        )
    after = decode_cursor(cursor)
    if after:
        query = query.where(EventProfile.id > after)
    rows = list((await session.execute(query.order_by(EventProfile.id).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda p: p.id)
    users = await identity.get_cards(session, [p.user_id for p in rows])
    return [
        EventCardOut(
            user_id=p.user_id,
            display_name=p.display_name,
            photo_url=users[p.user_id].photo_url,
            headline=p.headline,
            offer_text=p.offer_text,
        )
        for p in rows
        if users[p.user_id].active
    ], nxt


# --- goals -----------------------------------------------------------------------------


def goal_out(goal: Goal) -> GoalOut:
    return GoalOut(
        id=goal.id,
        intent=goal.intent,
        target=Target(**goal.target),
        offer=goal.offer,
        raw_input=goal.raw_input,
        priority=goal.priority,
        status=goal.status,
    )


async def parse_goal(text: str, user_id: str, event_id: str) -> GoalDraftOut | None:
    """AI parse; does NOT save. None means "open the manual form" (06 §4.1 fallback)."""
    try:
        result = await ai.run_task(
            "goal_parser", ai.user_data("goal", text), user_id=user_id, event_id=event_id
        )
    except ai.AiUnavailable:
        return None
    draft = ai.parsed(result, ai.schemas.GoalDraft)
    return GoalDraftOut(
        intent=draft.intent,
        target=Target(**draft.target.model_dump()),
        offer=(draft.offer or None) and draft.offer[:300],
        priority=1,
        confidence=draft.confidence,
        raw_input=text,
    )


async def list_goals(session: AsyncSession, profile_id: str) -> list[Goal]:
    return list(
        (
            await session.execute(
                select(Goal)
                .where(Goal.event_profile_id == profile_id, Goal.status == "active")
                .order_by(Goal.priority)
            )
        ).scalars()
    )


async def create_goal(session: AsyncSession, profile: EventProfile, data: GoalIn) -> Goal:
    await _screen(
        " \n ".join(
            filter(None, [data.offer, data.raw_input, *data.target.roles, *data.target.industries])
        ),
        profile.user_id,
        profile.event_id,
    )
    active = (
        await session.execute(
            select(func.count())
            .select_from(Goal)
            .where(Goal.event_profile_id == profile.id, Goal.status == "active")
        )
    ).scalar_one()
    if active >= 3:
        raise errors.GoalLimit
    goal = Goal(
        id=new_id("gol"),
        event_profile_id=profile.id,
        intent=data.intent,
        target=data.target.model_dump(),
        offer=data.offer,
        raw_input=data.raw_input,
        priority=data.priority,
        status="active",
    )
    session.add(goal)
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise errors.PriorityTaken from e
    await _schedule_embed(profile.id)
    return goal


async def _own_goal(session: AsyncSession, goal_id: str, user_id: str) -> tuple[Goal, EventProfile]:
    row = (
        await session.execute(
            select(Goal, EventProfile)
            .join(EventProfile, EventProfile.id == Goal.event_profile_id)
            .where(Goal.id == goal_id, EventProfile.user_id == user_id, Goal.status == "active")
        )
    ).one_or_none()
    if row is None:
        raise NotFound
    return row[0], row[1]


async def update_goal(
    session: AsyncSession, goal_id: str, user_id: str, patch: GoalPatchIn
) -> Goal:
    goal, profile = await _own_goal(session, goal_id, user_id)
    data: dict[str, Any] = patch.model_dump(exclude_unset=True)
    if data.get("offer"):
        await _screen(data["offer"], user_id, profile.event_id)
    for field, value in data.items():
        setattr(goal, field, value)
    goal.ask_embedding = goal.offer_embedding = None  # stale until re-embedded
    try:
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        raise errors.PriorityTaken from e
    await _schedule_embed(profile.id)
    return goal


async def archive_goal(session: AsyncSession, goal_id: str, user_id: str) -> None:
    goal, profile = await _own_goal(session, goal_id, user_id)
    goal.status = "archived"
    await session.commit()
    await _schedule_embed(profile.id)


# --- embedding (05 embedding contract) -------------------------------------------------


def ask_text(goal: Goal) -> str:
    t = goal.target
    return (
        f"{_INTENT_PHRASE[goal.intent]}. Looking for: roles={', '.join(t.get('roles', []))}; "
        f"industries={', '.join(t.get('industries', []))}; "
        f"stage={', '.join(t.get('stage', []))}. {goal.raw_input or ''}"
    )


def offer_text(goal: Goal, profile: EventProfile) -> str:
    return f"{goal.offer or ''}. Profile: {profile.headline or ''}. {profile.offer_text or ''}"
