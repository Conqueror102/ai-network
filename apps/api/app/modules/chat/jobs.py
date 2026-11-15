from datetime import timedelta

import structlog
from sqlalchemy import func, select

from app.core import clock, jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.ai import public as ai
from app.modules.chat import service
from app.modules.chat.models import Conversation, Message
from app.modules.matching import public as matching
from app.modules.profiles import public as profiles

log = structlog.get_logger()
DIED_AFTER = timedelta(hours=48)


@jobs.job("chat.icebreakers", timeout_s=30)
async def icebreakers(conversation_id: str) -> None:
    """Seed a new conversation with openers both people can see (01 §8.2, 06 §4.3).
    Idempotent: one icebreakers block per conversation. AI down -> template."""
    async with UnitOfWork() as session:
        conv = await session.get(Conversation, conversation_id, with_for_update=True)
        if conv is None:
            return
        seeded = (
            await session.execute(
                select(Message.id).where(
                    Message.conversation_id == conv.id, Message.kind == "icebreakers"
                )
            )
        ).first()
        if seeded:
            return
        chips, _ = await matching.match_context(session, conv.event_id, conv.user_a, conv.user_b)
        cards = await profiles.get_event_cards(session, conv.event_id, [conv.user_a, conv.user_b])
        source = (
            f"CHIPS: {' | '.join(chips)}\n"
            f"Person one: {ai.user_data('card_one', _line(cards[conv.user_a]))}\n"
            f"Person two: {ai.user_data('card_two', _line(cards[conv.user_b]))}"
        )
        options: list[str] = []
        try:
            result = await ai.run_task("icebreakers", source, event_id=conv.event_id)
            options = [
                ai.validators.clamp(o, 120)
                for o in ai.parsed(result, ai.schemas.Options).options[:3]
                if o.strip() and not ai.validators.contains_contact_details(o)
            ]
        except ai.AiUnavailable:
            log.warning("icebreakers_ai_unavailable", conversation_id=conversation_id)
        if not options:
            topic = chips[0] if chips else "this event"
            options = [
                f"What brought you here? I saw we overlap on {topic}.",
                "What are you hoping to get out of today?",
            ]
        msg = await service._add(
            session,
            conv,
            sender_id=None,
            kind="icebreakers",
            body="Wingman suggestions",
            payload={"options": options, "chips": chips},
        )
        users = [conv.user_a, conv.user_b]
    await service._fan_out(conv, msg, to=users)


def _line(card: profiles.EventCardOut) -> str:
    return ". ".join(x for x in (card.display_name, card.headline, card.offer_text) if x)


@jobs.job("chat.meet_reminder")
async def meet_reminder(message_id: str) -> None:
    """Ten minutes before an accepted meeting, remind both people (07 §2)."""
    async with UnitOfWork() as session:
        proposal = await session.get(Message, message_id)
        if proposal is None or (proposal.payload or {}).get("status") != "accepted":
            return
        if (proposal.payload or {}).get("reminded"):
            return
        conv = await session.get(Conversation, proposal.conversation_id)
        if conv is None:
            return
        proposal.payload = {**(proposal.payload or {}), "reminded": True}
        outbox.emit(
            session,
            "chat.meet_reminder",
            {
                "conversation_id": conv.id,
                "event_id": conv.event_id,
                "user_ids": [conv.user_a, conv.user_b],
                "meeting_point": proposal.payload["meeting_point"],
                "at": proposal.payload["at"],
            },
        )


@jobs.cron("chat.mark_died", hour={3}, minute={20})
async def mark_died() -> None:
    """Nightly label for the learning loop (05 §8): a chat with at least two messages,
    silent for 48 hours, that never led to a meeting."""
    cutoff = clock.now() - DIED_AFTER
    async with UnitOfWork() as session:
        texts = (
            select(Message.conversation_id, func.count().label("n"))
            .where(Message.kind == "text")
            .group_by(Message.conversation_id)
            .subquery()
        )
        met = select(Message.conversation_id).where(
            Message.kind == "system", Message.payload.has_key("meet_message_id")
        )
        rows = (
            await session.execute(
                select(Conversation)
                .join(texts, texts.c.conversation_id == Conversation.id)
                .where(
                    texts.c.n >= 2,
                    Conversation.last_message_at < cutoff,
                    Conversation.died_logged.is_(False),
                    Conversation.id.not_in(met),
                )
                .limit(500)
                .with_for_update(of=Conversation, skip_locked=True)
            )
        ).scalars()
        for conv in rows:
            conv.died_logged = True
            await matching.record_signal(
                session, conv.event_id, conv.user_a, conv.user_b, "chat_died"
            )


MESSAGE_KEEP = timedelta(days=730)


@jobs.cron("chat.retention", hour={2}, minute={30})
async def retention() -> None:
    """Messages are kept for 24 months, then deleted (02 retention; shown in-app)."""
    from sqlalchemy import delete

    async with UnitOfWork() as session:
        res = await session.execute(
            delete(Message).where(Message.created_at < clock.now() - MESSAGE_KEEP)
        )
    log.info("chat_retention", messages=res.rowcount or 0)  # type: ignore[attr-defined]
