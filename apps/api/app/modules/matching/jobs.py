import json

import structlog
from sqlalchemy import select

from app.core import jobs
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.events import public as events
from app.modules.matching import scoring, service
from app.modules.matching.models import MatchFeedItem
from app.modules.profiles import public as profiles
from app.modules.realtime import public as realtime

log = structlog.get_logger()
FANOUT_DEBOUNCE_S = 30


def job_id(event_id: str, user_id: str) -> str:
    return f"match:{event_id}:{user_id}"


@jobs.job("matching.compute_for_user", timeout_s=60)
async def compute_for_user(event_id: str, user_id: str, fanout: bool = True) -> None:
    async with UnitOfWork() as session:
        stale = await service.compute_for_user(session, event_id, user_id)
    await realtime.publish_user(user_id, "matches.updated", {"event_id": event_id})
    await jobs.enqueue("matching.explain", event_id, user_id, job_id=f"why:{event_id}:{user_id}")
    if fanout:
        # People who now score this user well get their feed refreshed once. Those
        # refreshes do not fan out again, so there is no ping-pong.
        for peer in stale:
            await jobs.enqueue(
                "matching.compute_for_user",
                event_id,
                peer,
                False,
                job_id=job_id(event_id, peer),
                defer_s=FANOUT_DEBOUNCE_S,
            )


@jobs.job("matching.explain", timeout_s=120)
async def explain(event_id: str, user_id: str) -> None:
    """Write the "why you two" line for every feed item that lacks one (06 §4.2).
    Grounded or replaced: an explanation naming a fact that is not in the input is
    retried once, then swapped for the template."""
    async with UnitOfWork() as session:
        peers = list(
            (
                await session.execute(
                    select(MatchFeedItem.peer_id).where(
                        MatchFeedItem.event_id == event_id, MatchFeedItem.user_id == user_id
                    )
                )
            ).scalars()
        )
        cards = await profiles.get_event_cards(session, event_id, [user_id, *peers])
        for peer in peers:
            row = await service.get_score(session, event_id, user_id, peer)
            if row is None:
                continue
            viewer_is_a = row.user_a == user_id
            if (row.why_a if viewer_is_a else row.why_b) is not None:
                continue
            chips = scoring.chips_for(row.components, viewer_is_a)
            mine, theirs = cards[user_id], cards[peer]
            source = (
                f"CHIPS: {' | '.join(chips)}\n"
                f"Match signals: {json.dumps(row.components.get('matched', []))}\n"
                f"Reader: {ai.user_data('reader_card', _line(mine))}\n"
                f"Other person: {ai.user_data('other_card', _line(theirs))}"
            )
            text: str | None = None
            try:
                for _ in range(2):
                    result = await ai.run_task(
                        "match_explainer", source, user_id=user_id, event_id=event_id
                    )
                    candidate = ai.parsed(result, ai.schemas.Explanation).text.strip()
                    if (
                        candidate
                        and len(candidate) <= 140
                        and not ai.validators.ungrounded_terms(candidate, source)
                        and not ai.validators.contains_contact_details(candidate)
                    ):
                        text = candidate
                        break
            except ai.AiUnavailable:
                log.warning("explain_ai_unavailable", event_id=event_id)
                return  # the feed shows the template until the next compute retries
            text = text or service.fallback_why(chips)
            if viewer_is_a:
                row.why_a = text
            else:
                row.why_b = text


def _line(card: profiles.EventCardOut) -> str:
    return ". ".join(x for x in (card.display_name, card.headline, card.offer_text) if x)


@jobs.cron("matching.recompute_live", minute={5, 35})
async def recompute_live() -> None:
    """Every 30 minutes while an event is live (05 §8): refresh presence and catch
    anything a per-user trigger missed."""
    async with UnitOfWork() as session:
        for event_id in await events.live_event_ids(session):
            for user_id in await profiles.user_ids_with_profile(session, event_id):
                await jobs.enqueue(
                    "matching.compute_for_user",
                    event_id,
                    user_id,
                    False,
                    job_id=job_id(event_id, user_id),
                )
