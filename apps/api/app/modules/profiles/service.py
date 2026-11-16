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
    DirectoryCardOut,
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
    return MyEventProfileOut(
        **card.model_dump(), visibility=profile.visibility, open_to_all=profile.open_to_all
    )


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


def _like(value: str) -> str:
    return f"%{value.replace('%', '').replace('_', '')}%"


def _discoverable(event_id: str, me: str) -> list[Any]:
    """Who may appear in the directory and in search for `me`: checked in, visible,
    open to meeting anyone, not blocked either way, not me."""
    return [
        EventProfile.event_id == event_id,
        EventProfile.visibility != "hidden",
        EventProfile.open_to_all.is_(True),
        EventProfile.user_id != me,
        EventProfile.user_id.in_(events.checked_in_subquery(event_id)),
        safety.not_blocked(me, EventProfile.user_id),
    ]


async def _require_browsing(session: AsyncSession, event_id: str, me: str) -> None:
    mine = await require_profile(session, event_id, me)
    if mine.visibility == "hidden":
        raise errors.DirectoryRequiresVisibility  # reciprocity (01 §4)


async def _directory_cards(
    session: AsyncSession, rows: list[EventProfile]
) -> list[DirectoryCardOut]:
    if not rows:
        return []
    users = await identity.get_cards(session, [p.user_id for p in rows])
    intents: dict[str, list[str]] = {}
    for profile_id, intent in (
        await session.execute(
            select(Goal.event_profile_id, Goal.intent)
            .where(Goal.event_profile_id.in_([p.id for p in rows]), Goal.status == "active")
            .order_by(Goal.priority)
        )
    ).all():
        if intent not in intents.setdefault(profile_id, []):
            intents[profile_id].append(intent)
    return [
        DirectoryCardOut(
            user_id=p.user_id,
            display_name=p.display_name,
            photo_url=users[p.user_id].photo_url,
            headline=p.headline,
            offer_text=p.offer_text,
            role_title=users[p.user_id].role_title,
            company=users[p.user_id].company,
            industry=users[p.user_id].industry,
            looking_for=intents.get(p.id, []),
        )
        for p in rows
        if users[p.user_id].active
    ]


def _keyword(q: str) -> Any:
    like = _like(q)
    return or_(
        EventProfile.display_name.ilike(like),
        EventProfile.headline.ilike(like),
        EventProfile.offer_text.ilike(like),
        EventProfile.user_id.in_(identity.user_ids_matching(text=q)),
    )


async def directory(
    session: AsyncSession,
    event_id: str,
    me: str,
    q: str | None,
    cursor: str | None,
    limit: int,
    *,
    role: str | None = None,
    industry: str | None = None,
    company: str | None = None,
    intent: str | None = None,
) -> tuple[list[DirectoryCardOut], str | None]:
    """Browse everyone at the event who is open to being found. Filters combine with
    AND. Nothing here depends on the match score: anyone listed can be waved at."""
    await _require_browsing(session, event_id, me)
    query = select(EventProfile).where(*_discoverable(event_id, me))
    if q:
        query = query.where(_keyword(q))
    if role or industry or company:
        query = query.where(
            EventProfile.user_id.in_(
                identity.user_ids_matching(role=role, industry=industry, company=company)
            )
        )
    if intent:
        query = query.where(
            EventProfile.id.in_(
                select(Goal.event_profile_id).where(Goal.status == "active", Goal.intent == intent)
            )
        )
    after = decode_cursor(cursor)
    if after:
        query = query.where(EventProfile.id > after)
    rows = list((await session.execute(query.order_by(EventProfile.id).limit(limit + 1))).scalars())
    rows, nxt = paginate(rows, limit, lambda p: p.id)
    return await _directory_cards(session, rows), nxt


SEARCH_LIMIT = 20
SEARCH_MIN_SIM = 0.15  # below this a result is noise, not a weak match


async def search(
    session: AsyncSession, event_id: str, me: str, text: str
) -> tuple[list[DirectoryCardOut], str]:
    """ "A lawyer who works with startups": rank people by how well what they offer and
    who they are fits the description. One-directional on purpose: it ignores whether
    the searcher fits the other person's goals. The other person still decides, because
    contact starts with a wave they can silently decline.

    Falls back to a keyword match when embeddings are unavailable."""
    await _require_browsing(session, event_id, me)
    conds = _discoverable(event_id, me)
    try:
        vectors, _ = await ai.embed([text], input_type="query")
    except ai.AiUnavailable:
        rows = list(
            (
                await session.execute(
                    select(EventProfile)
                    .where(*conds, _keyword(text))
                    .order_by(EventProfile.id)
                    .limit(SEARCH_LIMIT)
                )
            ).scalars()
        )
        return await _directory_cards(session, rows), "keyword"
    vector = vectors[0]
    d_profile = EventProfile.profile_embedding.cosine_distance(vector)
    d_goal = Goal.offer_embedding.cosine_distance(vector)
    hits = [
        *(
            await session.execute(
                select(EventProfile.id, d_profile)
                .where(*conds, EventProfile.profile_embedding.is_not(None))
                .order_by(d_profile)
                .limit(SEARCH_LIMIT)
            )
        ).all(),
        *(
            await session.execute(
                select(EventProfile.id, d_goal)
                .join(Goal, Goal.event_profile_id == EventProfile.id)
                .where(*conds, Goal.status == "active", Goal.offer_embedding.is_not(None))
                .order_by(d_goal)
                .limit(SEARCH_LIMIT)
            )
        ).all(),
    ]
    best: dict[str, float] = {}
    for profile_id, dist in hits:
        sim = 0.0 if dist is None or dist != dist else 1.0 - float(dist)  # NaN: zero vector
        if sim >= SEARCH_MIN_SIM:
            best[profile_id] = max(best.get(profile_id, 0.0), sim)
    ranked = sorted(best, key=lambda pid: (-best[pid], pid))[:SEARCH_LIMIT]
    if not ranked:
        return [], "smart"
    by_id = {
        p.id: p
        for p in (
            await session.execute(select(EventProfile).where(EventProfile.id.in_(ranked)))
        ).scalars()
    }
    return await _directory_cards(session, [by_id[pid] for pid in ranked]), "smart"


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
