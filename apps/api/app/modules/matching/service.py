"""The matching pipeline (05): filter, generate candidates, score pairs, select a feed."""

import math
import time
from dataclasses import asdict
from typing import Any

from sqlalchemy import and_, case, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, presence
from app.core.errors import NotFound, ValidationFailed
from app.core.ids import new_id
from app.modules.connections import public as connections
from app.modules.events import public as events
from app.modules.matching import scoring
from app.modules.matching.models import (
    MatchFeedback,
    MatchFeedItem,
    MatchFeedState,
    MatchingConfig,
    MatchScore,
)
from app.modules.matching.schemas import AskedForCard, FeedOut, MatchCard
from app.modules.matching.scoring import Config
from app.modules.profiles import public as profiles

_cfg_cache: tuple[float, Config] | None = None
CONFIG_TTL_S = 60.0
EXCLUDING_SIGNALS = ("feed_skip", "wave_sent")


# --- config ----------------------------------------------------------------------------


async def load_config(session: AsyncSession, *, fresh: bool = False) -> Config:
    global _cfg_cache
    if not fresh and _cfg_cache and time.monotonic() - _cfg_cache[0] < CONFIG_TTL_S:
        return _cfg_cache[1]
    row = await session.get(MatchingConfig, "default")
    cfg = Config().with_overrides(row.values if row else {})
    _cfg_cache = (time.monotonic(), cfg)
    return cfg


def clear_config_cache() -> None:
    global _cfg_cache
    _cfg_cache = None


async def set_config(
    session: AsyncSession, values: dict[str, float], staff_id: str
) -> tuple[Config, dict[str, Any]]:
    unknown = sorted(set(values) - set(asdict(Config())))
    if unknown:
        raise ValidationFailed("Unknown matching constants", details={"unknown": unknown})
    row = await session.get(MatchingConfig, "default")
    if row is None:
        row = MatchingConfig(id="default", values={})
        session.add(row)
    row.values = dict(values)
    row.updated_by = staff_id
    await session.commit()
    clear_config_cache()
    return await load_config(session, fresh=True), row.values


# --- signals ---------------------------------------------------------------------------


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


async def get_score(session: AsyncSession, event_id: str, a: str, b: str) -> MatchScore | None:
    ua, ub = _pair(a, b)
    return await session.get(MatchScore, (event_id, ua, ub))


async def record_signal(
    session: AsyncSession, event_id: str, user_id: str, peer_id: str, signal: str
) -> None:
    """Log a labelled example with the score components frozen at this moment (05 §6)."""
    row = await get_score(session, event_id, user_id, peer_id)
    session.add(
        MatchFeedback(
            id=new_id("mfb"),
            event_id=event_id,
            user_id=user_id,
            peer_id=peer_id,
            signal=signal,
            components=row.components if row else {},
        )
    )
    if signal in EXCLUDING_SIGNALS:
        pairs = [and_(MatchFeedItem.user_id == user_id, MatchFeedItem.peer_id == peer_id)]
        if signal == "wave_sent":  # a wave removes the pair from both feeds
            pairs.append(and_(MatchFeedItem.user_id == peer_id, MatchFeedItem.peer_id == user_id))
        await session.execute(
            delete(MatchFeedItem).where(MatchFeedItem.event_id == event_id, or_(*pairs))
        )


async def excluded_ids(session: AsyncSession, event_id: str, me: str) -> set[str]:
    """People who must not appear in my feed: I skipped them, a wave exists either way,
    or we are already connected (05 §2)."""
    rows = (
        await session.execute(
            select(MatchFeedback.user_id, MatchFeedback.peer_id).where(
                MatchFeedback.event_id == event_id,
                or_(
                    and_(MatchFeedback.user_id == me, MatchFeedback.signal.in_(EXCLUDING_SIGNALS)),
                    and_(MatchFeedback.peer_id == me, MatchFeedback.signal == "wave_sent"),
                ),
            )
        )
    ).all()
    out = {b if a == me else a for a, b in rows}
    return out | await connections.connected_peer_ids(session, event_id, me)


async def _warmth(session: AsyncSession, event_id: str, user_ids: list[str]) -> dict[str, float]:
    """Smoothed accept rate per user. Private: only ever used inside the score."""
    received = dict(
        (
            await session.execute(
                select(MatchFeedback.peer_id, func.count())
                .where(
                    MatchFeedback.event_id == event_id,
                    MatchFeedback.signal == "wave_sent",
                    MatchFeedback.peer_id.in_(user_ids),
                )
                .group_by(MatchFeedback.peer_id)
            )
        ).all()
    )
    accepts = dict(
        (
            await session.execute(
                select(MatchFeedback.user_id, func.count())
                .where(
                    MatchFeedback.event_id == event_id,
                    MatchFeedback.signal == "wave_accepted",
                    MatchFeedback.user_id.in_(user_ids),
                )
                .group_by(MatchFeedback.user_id)
            )
        ).all()
    )
    return {u: scoring.warmth(accepts.get(u, 0), received.get(u, 0)) for u in user_ids}


async def _damping(
    session: AsyncSession, event_id: str, me: str, peers: list[str], cfg: Config
) -> dict[str, float]:
    """Popularity damping (05 §9): someone already in more than 15% of feeds is
    pushed down a little per extra appearance."""
    feeds = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MatchFeedState)
                .where(MatchFeedState.event_id == event_id)
            )
        ).scalar_one()
    )
    if feeds < cfg.damping_min_feeds or not peers:
        return {}
    allowed = math.ceil(cfg.damping_share * feeds)
    rows = (
        await session.execute(
            select(MatchFeedItem.peer_id, func.count())
            .where(
                MatchFeedItem.event_id == event_id,
                MatchFeedItem.user_id != me,
                MatchFeedItem.peer_id.in_(peers),
            )
            .group_by(MatchFeedItem.peer_id)
        )
    ).all()
    return {
        peer: min(cfg.damping_cap, cfg.damping_step * (n - allowed))
        for peer, n in rows
        if n > allowed
    }


# --- pipeline --------------------------------------------------------------------------


async def _clear_feed(session: AsyncSession, event_id: str, user_id: str) -> None:
    await session.execute(
        delete(MatchFeedItem).where(
            MatchFeedItem.event_id == event_id, MatchFeedItem.user_id == user_id
        )
    )


async def _touch_state(session: AsyncSession, event_id: str, user_id: str) -> None:
    now = clock.now()
    await session.execute(
        insert(MatchFeedState)
        .values(event_id=event_id, user_id=user_id, computed_at=now)
        .on_conflict_do_update(index_elements=["event_id", "user_id"], set_={"computed_at": now})
    )


async def compute_for_user(session: AsyncSession, event_id: str, user_id: str) -> list[str]:
    """Stages 1 to 5 for one user. Idempotent: scores are upserted, the feed is replaced.
    Returns peers whose own feed may now be stale (they score this user well)."""
    cfg = await load_config(session)
    await _clear_feed(session, event_id, user_id)
    await _touch_state(session, event_id, user_id)
    me = (await profiles.load_profiles(session, event_id, [user_id])).get(user_id)
    if (
        me is None
        or me.visibility == "hidden"  # reciprocity: unseen people do not get a feed
        or not await events.is_checked_in(session, event_id, user_id)
    ):
        return []

    # stage 1 + 2: hard filters in SQL, nearest offers per ask
    exclude = await excluded_ids(session, event_id, user_id)
    queries = [g.ask_embedding for g in me.goals if g.ask_embedding is not None]
    if not queries and me.profile_embedding is not None:
        queries = [me.profile_embedding]
    best: dict[str, float] = {}
    for vector in queries:
        for peer_id, _, sim in await profiles.nearest_offers(
            session, event_id, user_id, vector, exclude=exclude, limit=cfg.per_goal_limit
        ):
            best[peer_id] = max(best.get(peer_id, 0.0), sim)
    candidate_ids = sorted(best, key=lambda p: -best[p])[: cfg.k]
    candidates = await profiles.load_profiles(session, event_id, candidate_ids)
    if not candidates:
        return []

    # stage 3 + 4: pairwise fit both ways, then the pair score
    everyone = [user_id, *candidates]
    here = await events.checked_in_today(session, event_id, everyone)
    present = here & await presence.active_ids(everyone)
    warmth = await _warmth(session, event_id, everyone)
    rows: list[dict[str, Any]] = []
    mine: dict[str, float] = {}
    theirs: dict[str, float] = {}
    now = clock.now()
    for peer_id, peer in candidates.items():
        me_is_a = user_id < peer_id
        a, b = (me, peer) if me_is_a else (peer, me)
        score_a, score_b, components = scoring.pair_scores(
            scoring.fit(a, b, cfg),
            scoring.fit(b, a, cfg),
            both_present=user_id in present and peer_id in present,
            warmth_a=warmth[a.user_id],
            warmth_b=warmth[b.user_id],
            cfg=cfg,
        )
        mine[peer_id], theirs[peer_id] = (score_a, score_b) if me_is_a else (score_b, score_a)
        rows.append(
            {
                "event_id": event_id,
                "user_a": a.user_id,
                "user_b": b.user_id,
                "score_a": score_a,
                "score_b": score_b,
                "components": components,
                "computed_at": now,
            }
        )
    stmt = insert(MatchScore).values(rows)
    same = MatchScore.components["sig"].astext == stmt.excluded.components["sig"].astext
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=["event_id", "user_a", "user_b"],
            set_={
                "score_a": stmt.excluded.score_a,
                "score_b": stmt.excluded.score_b,
                "components": stmt.excluded.components,
                "computed_at": stmt.excluded.computed_at,
                # an explanation survives until what it explains changes (05 §7.3)
                "why_a": case((same, MatchScore.why_a), else_=None),
                "why_b": case((same, MatchScore.why_b), else_=None),
            },
        )
    )

    # stage 5: selection
    damping = await _damping(session, event_id, user_id, list(candidates), cfg)
    ranked = sorted(
        ((p, mine[p] - damping.get(p, 0.0)) for p in candidates), key=lambda r: (-r[1], r[0])
    )
    feed = scoring.select_feed(ranked, {p: c.profile_embedding for p, c in candidates.items()}, cfg)
    if feed:
        await session.execute(
            insert(MatchFeedItem).values(
                [
                    {
                        "event_id": event_id,
                        "user_id": user_id,
                        "peer_id": p,
                        "position": i,
                        "wildcard": wild,
                    }
                    for i, (p, wild) in enumerate(feed)
                ]
            )
        )
    stale = sorted((p for p in candidates if theirs[p] >= cfg.min_score), key=lambda p: -theirs[p])
    return stale[: cfg.fanout]


# --- read ------------------------------------------------------------------------------


def fallback_why(chips: list[str]) -> str:
    return f"You match on {', '.join(chips)}." if chips else "Your goals line up."


async def feed(session: AsyncSession, event_id: str, me: str) -> tuple[FeedOut, bool]:
    """Returns (feed, computed_now). Exclusions are re-applied at read time so a block,
    a skip or a profile going hidden takes effect immediately, not at the next recompute."""
    cfg = await load_config(session)
    state = await session.get(MatchFeedState, (event_id, me))
    computed_now = False
    if state is None:
        await compute_for_user(session, event_id, me)
        await session.commit()
        state = await session.get(MatchFeedState, (event_id, me))
        computed_now = True
    items = list(
        (
            await session.execute(
                select(MatchFeedItem)
                .where(MatchFeedItem.event_id == event_id, MatchFeedItem.user_id == me)
                .order_by(MatchFeedItem.position)
            )
        ).scalars()
    )
    peer_ids = [i.peer_id for i in items]
    ok = await profiles.showable_ids(session, event_id, me, peer_ids)
    ok -= await excluded_ids(session, event_id, me)
    items = [i for i in items if i.peer_id in ok]
    cards = await profiles.get_event_cards(session, event_id, [i.peer_id for i in items])
    out = []
    for item in items:
        row = await get_score(session, event_id, me, item.peer_id)
        if row is None:
            continue
        viewer_is_a = row.user_a == me
        chips = scoring.chips_for(row.components, viewer_is_a)
        score = row.score_a if viewer_is_a else row.score_b
        card = cards[item.peer_id]
        out.append(
            MatchCard(
                user_id=item.peer_id,
                display_name=card.display_name,
                photo_url=card.photo_url,
                headline=card.headline,
                offer_text=card.offer_text,
                why=(row.why_a if viewer_is_a else row.why_b) or fallback_why(chips),
                matched_chips=chips,
                wildcard=item.wildcard,
                score_bucket="high" if score >= cfg.high_bucket else "medium",
            )
        )
    asked = await _asked_for(session, event_id, me, {i.peer_id for i in items}, cfg)
    others = await profiles.profile_count(session, event_id) - 1
    return (
        FeedOut(
            items=out,
            asked_for=asked,
            computed_at=state.computed_at if state else None,
            warming_up=others < cfg.warmup_min,
        ),
        computed_now,
    )


def _my_side(row: MatchScore, me: str) -> dict[str, Any]:
    """The half of a pair's components that describes what `me` wants."""
    d = "ab" if row.user_a == me else "ba"
    return next((m for m in row.components.get("matched", []) if m.get("dir") == d), {})


async def _asked_for(
    session: AsyncSession,
    event_id: str,
    me: str,
    in_feed: set[str],
    cfg: scoring.Config,
) -> list[AskedForCard]:
    """People who fit what I am looking for even though the pair did not make my feed,
    usually because I do not fit their goals. Ranked by my side of the fit only.

    Left out: anyone already in the feed, anyone I skipped, waved at or connected with,
    hidden or blocked people, and people who switched off "open to meeting anyone"."""
    if cfg.asked_for_size <= 0:
        return []
    rows = list(
        (
            await session.execute(
                select(MatchScore).where(
                    MatchScore.event_id == event_id,
                    or_(MatchScore.user_a == me, MatchScore.user_b == me),
                )
            )
        ).scalars()
    )
    wanted: list[tuple[float, str, MatchScore]] = []
    for row in rows:
        peer = row.user_b if row.user_a == me else row.user_a
        mine = float(row.components.get("fit_ab" if row.user_a == me else "fit_ba", 0.0))
        if peer not in in_feed and mine >= cfg.asked_for_min:
            wanted.append((mine, peer, row))
    if not wanted:
        return []
    ids = [p for _, p, _ in wanted]
    ok = await profiles.showable_ids(session, event_id, me, ids)
    ok &= await profiles.open_ids(session, event_id, ids)
    ok -= await excluded_ids(session, event_id, me)
    wanted = sorted((w for w in wanted if w[1] in ok), key=lambda w: (-w[0], w[1]))
    wanted = wanted[: cfg.asked_for_size]
    cards = await profiles.get_event_cards(session, event_id, [p for _, p, _ in wanted])
    out = []
    for _, peer, row in wanted:
        side = _my_side(row, me)
        chips = [str(h).split(":", 1)[-1] for h in side.get("filter_hits", [])]
        label = scoring.INTENT_LABEL.get(side.get("b_intent") or "")
        if label and label not in chips:
            chips.append(label)
        card = cards[peer]
        out.append(
            AskedForCard(
                user_id=peer,
                display_name=card.display_name,
                photo_url=card.photo_url,
                headline=card.headline,
                offer_text=card.offer_text,
                why="Fits what you are looking for.",
                matched_chips=chips[:4],
            )
        )
    return out


async def in_feed(session: AsyncSession, event_id: str, me: str, peer_id: str) -> bool:
    """True when the engine put `peer_id` in my feed, i.e. the match is mutual enough."""
    return (await session.get(MatchFeedItem, (event_id, me, peer_id))) is not None


async def skip(session: AsyncSession, event_id: str, me: str, peer_id: str) -> None:
    if peer_id == me or not await profiles.showable_ids(session, event_id, me, [peer_id]):
        raise NotFound
    already = (
        await session.execute(
            select(MatchFeedback.id).where(
                MatchFeedback.event_id == event_id,
                MatchFeedback.user_id == me,
                MatchFeedback.peer_id == peer_id,
                MatchFeedback.signal == "feed_skip",
            )
        )
    ).first()
    if not already:
        await record_signal(session, event_id, me, peer_id, "feed_skip")
    await session.commit()


async def forget_user(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        delete(MatchScore).where(or_(MatchScore.user_a == user_id, MatchScore.user_b == user_id))
    )
    await session.execute(
        delete(MatchFeedItem).where(
            or_(MatchFeedItem.user_id == user_id, MatchFeedItem.peer_id == user_id)
        )
    )
    await session.execute(delete(MatchFeedState).where(MatchFeedState.user_id == user_id))
