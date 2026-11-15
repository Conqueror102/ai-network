"""Sponsors' public surface. By design there is no function here that returns a user
id: sponsors get aggregates only (08 §6, doc 11 §5)."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.sponsors import service
from app.modules.sponsors.service import SponsorTextRejected, screen_text


@dataclass(frozen=True)
class SponsorInfo:
    id: str
    event_id: str
    name: str
    active: bool


async def get_info(session: AsyncSession, event_id: str, sponsor_id: str) -> SponsorInfo:
    s = await service.get(session, event_id, sponsor_id)
    return SponsorInfo(s.id, s.event_id, s.name, s.status == "active")


__all__ = ["SponsorInfo", "SponsorTextRejected", "get_info", "screen_text"]
