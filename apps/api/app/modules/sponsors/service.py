from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, ValidationFailed
from app.core.ids import new_id
from app.modules.ai import public as ai
from app.modules.sponsors.models import Sponsor
from app.modules.sponsors.schemas import SponsorIn, SponsorOut


class SponsorTextRejected(ValidationFailed):
    code, message = "sponsor_text_rejected", "This text was not accepted. Try different wording."


def out(s: Sponsor) -> SponsorOut:
    return SponsorOut(
        id=s.id, event_id=s.event_id, name=s.name, tagline=s.tagline, url=s.url, status=s.status
    )


async def screen_text(text: str, user_id: str, event_id: str) -> str:
    """Every sponsor text is screened on save (doc 11 §5). Returns the status to store:
    "active", or "held" for staff review when the screen cannot run. Fail closed."""
    try:
        verdict = await ai.screen(text, kind="sponsor_text", user_id=user_id, event_id=event_id)
    except ai.AiUnavailable:
        return "held"
    if not verdict.allow:
        raise SponsorTextRejected(details={"category": verdict.category})
    return "active"


async def create(session: AsyncSession, event_id: str, user_id: str, data: SponsorIn) -> Sponsor:
    status = await screen_text(f"{data.name}. {data.tagline or ''}", user_id, event_id)
    sponsor = Sponsor(
        id=new_id("spn"),
        event_id=event_id,
        name=data.name,
        tagline=data.tagline,
        url=str(data.url) if data.url else None,
        status=status,
    )
    session.add(sponsor)
    await session.commit()
    return sponsor


async def list_for_event(session: AsyncSession, event_id: str) -> list[Sponsor]:
    return list(
        (
            await session.execute(
                select(Sponsor)
                .where(Sponsor.event_id == event_id, Sponsor.status != "archived")
                .order_by(Sponsor.id)
            )
        ).scalars()
    )


async def get(session: AsyncSession, event_id: str, sponsor_id: str) -> Sponsor:
    sponsor = await session.get(Sponsor, sponsor_id)
    if sponsor is None or sponsor.event_id != event_id:  # tenant boundary: 404
        raise NotFound
    return sponsor


async def archive(session: AsyncSession, event_id: str, sponsor_id: str) -> None:
    sponsor = await get(session, event_id, sponsor_id)
    sponsor.status = "archived"
    await session.commit()
