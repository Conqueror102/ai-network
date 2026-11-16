"""Matching's public surface: other modules log signals and read match context here.
They never see scores."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.matching import scoring
from app.modules.matching.service import fallback_why, get_score, in_feed, record_signal


async def match_context(
    session: AsyncSession, event_id: str, viewer: str, peer: str
) -> tuple[list[str], str | None]:
    """(chips, why) as `viewer` sees `peer`. Empty when the pair was never scored."""
    row = await get_score(session, event_id, viewer, peer)
    if row is None:
        return [], None
    viewer_is_a = row.user_a == viewer
    chips = scoring.chips_for(row.components, viewer_is_a)
    return chips, (row.why_a if viewer_is_a else row.why_b) or fallback_why(chips)


__all__ = ["in_feed", "match_context", "record_signal"]
