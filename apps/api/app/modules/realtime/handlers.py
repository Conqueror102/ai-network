"""Domain events -> WebSocket envelopes (07 §1 event table). Push and the in-app inbox
are the notifications module's job; this file only does live delivery."""

from typing import Any

from app.core import outbox
from app.core.db.uow import UnitOfWork
from app.modules.events import public as events
from app.modules.profiles import public as profiles
from app.modules.realtime.public import publish_event, publish_user


@outbox.subscribe("waves.received")
async def wave_received(p: dict[str, Any]) -> None:
    # no sender identity in the envelope: the client fetches the card over REST
    await publish_user(p["to_user"], "wave.received", {"wave_id": p["wave_id"]})


@outbox.subscribe("waves.accepted")
async def wave_accepted(p: dict[str, Any]) -> None:
    await publish_user(
        p["from_user"],
        "wave.accepted",
        {"wave_id": p["wave_id"], "conversation_id": p["conversation_id"]},
    )


@outbox.subscribe("waves.mutual")
async def wave_mutual(p: dict[str, Any]) -> None:
    a, b = p["user_ids"]
    async with UnitOfWork() as session:
        cards = await profiles.get_event_cards(session, p["event_id"], [a, b])
    for me, peer in ((a, b), (b, a)):
        await publish_user(
            me,
            "wave.mutual",
            {"conversation_id": p["conversation_id"], "peer_card": cards[peer].model_dump()},
        )


@outbox.subscribe("chat.conversation_created")
async def conversation_created(p: dict[str, Any]) -> None:
    for user_id in p["user_ids"]:
        await publish_user(
            user_id, "conversation.created", {"conversation_id": p["conversation_id"]}
        )


@outbox.subscribe("connections.exchange_scanned")
async def exchange_scanned(p: dict[str, Any]) -> None:
    await publish_user(p["user_id"], "exchange.pending", {"confirm_id": p["confirm_id"]})


@outbox.subscribe("connections.confirmed")
async def connection_confirmed(p: dict[str, Any]) -> None:
    a, b = p["user_ids"]
    async with UnitOfWork() as session:
        cards = await profiles.get_event_cards(session, p["event_id"], [a, b])
    for me, peer in ((a, b), (b, a)):
        await publish_user(
            me,
            "connection.confirmed",
            {"event_id": p["event_id"], "peer_card": cards[peer].model_dump()},
        )


@outbox.subscribe("events.announcement_created")
async def announcement(p: dict[str, Any]) -> None:
    await publish_event(
        p["event_id"],
        "attendee",
        "announcement.new",
        {k: v for k, v in p.items() if not k.startswith("_")},
    )


@outbox.subscribe("events.checked_in")
async def stats(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        count = await events.checked_in_count(session, p["event_id"])
    await publish_event(p["event_id"], "stats", "event.stats", {"checked_in": count})
