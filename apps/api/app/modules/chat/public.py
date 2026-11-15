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


async def assist_context(
    session: AsyncSession, conversation_id: str, me: str
) -> tuple[str, str, list[tuple[bool, str]]]:
    """For the wingman: (event_id, peer_id, last 10 messages as (mine, text)).
    Raises the same 404 as any chat route for non-participants and blocked pairs."""
    from app.modules.chat import service

    conv, rows = await service.recent_messages(session, conversation_id, me, 10)
    return conv.event_id, service.peer_of(conv, me), [(m.sender_id == me, m.body) for m in rows]


async def preview(session: AsyncSession, message_id: str) -> tuple[str, str] | None:
    """(kind, first 60 characters) for a push notification body."""
    from app.modules.chat.models import Message

    m = await session.get(Message, message_id)
    return None if m is None else (m.kind, m.body[:60])


async def counts(session: AsyncSession, event_id: str) -> dict[str, int]:
    """Aggregates for organizer reports."""
    from sqlalchemy import func

    from app.modules.chat.models import Message

    started = (
        await session.execute(
            select(func.count(func.distinct(Message.conversation_id)))
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.event_id == event_id, Message.kind == "text")
        )
    ).scalar_one()
    meetings = (
        await session.execute(
            select(func.count())
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Conversation.event_id == event_id,
                Message.kind == "system",
                Message.payload.has_key("meet_message_id"),
            )
        )
    ).scalar_one()
    return {"conversations_started": int(started), "meetings_planned": int(meetings)}


__all__ = ["assist_context", "counts", "open_conversation", "preview"]
