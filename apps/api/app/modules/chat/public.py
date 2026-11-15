"""Chat's public surface."""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox
from app.core.ids import new_id
from app.modules.chat.models import Conversation


async def open_conversation(
    session: AsyncSession, event_id: str, a: str, b: str, *, wave_id: str | None = None
) -> str:
    """Create (or return) the 1:1 conversation for a pair in an event. Idempotent."""
    ua, ub = (a, b) if a < b else (b, a)
    cid = new_id("cnv")
    inserted = (
        await session.execute(
            insert(Conversation)
            .values(id=cid, event_id=event_id, user_a=ua, user_b=ub, created_from_wave=wave_id)
            .on_conflict_do_nothing(index_elements=["event_id", "user_a", "user_b"])
            .returning(Conversation.id)
        )
    ).scalar_one_or_none()
    if inserted:
        outbox.emit(
            session,
            "chat.conversation_created",
            {"conversation_id": cid, "event_id": event_id, "user_ids": [ua, ub]},
        )
        return cid
    return (
        await session.execute(
            select(Conversation.id).where(
                Conversation.event_id == event_id,
                Conversation.user_a == ua,
                Conversation.user_b == ub,
            )
        )
    ).scalar_one()


__all__ = ["open_conversation"]
