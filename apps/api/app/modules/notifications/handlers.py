"""Domain events -> notifications (07 §2 catalogue)."""

from typing import Any

from app.core import jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.events import public as events
from app.modules.notifications.service import notify
from app.modules.profiles import public as profiles


async def _names(session: Any, event_id: str, user_ids: list[str]) -> dict[str, str]:
    cards = await profiles.get_event_cards(session, event_id, user_ids)
    return {uid: c.display_name for uid, c in cards.items()}


@outbox.subscribe("waves.received")
async def wave_received(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        # no name: curiosity and privacy (07 §2)
        await notify(
            session,
            p["to_user"],
            "wave",
            "New intro",
            f"Someone at {event.name} wants to meet you",
            data={"event_id": event.id, "wave_id": p["wave_id"]},
            collapse=f"wave:{event.id}",
            tz=event.timezone,
        )


@outbox.subscribe("waves.accepted")
async def wave_accepted(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        name = (await _names(session, event.id, [p["to_user"]]))[p["to_user"]]
        await notify(
            session,
            p["from_user"],
            "wave_accepted",
            "Intro accepted",
            f"{name} accepted your intro 🎉",
            data={"event_id": event.id, "conversation_id": p["conversation_id"]},
            tz=event.timezone,
        )


@outbox.subscribe("waves.mutual")
async def wave_mutual(p: dict[str, Any]) -> None:
    a, b = p["user_ids"]
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        names = await _names(session, event.id, [a, b])
        for me, peer in ((a, b), (b, a)):
            await notify(
                session,
                me,
                "wave_accepted",
                "You noticed each other",
                f"You and {names[peer]} noticed each other",
                data={"event_id": event.id, "conversation_id": p["conversation_id"]},
                tz=event.timezone,
            )


@outbox.subscribe("waves.resurfaced")
async def wave_resurfaced(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        name = (await _names(session, event.id, [p["from_user"]]))[p["from_user"]]
        await notify(
            session,
            p["to_user"],
            "wave",
            "Still interested?",
            f"Still want to connect with {name} from {event.name}?",
            data={"event_id": event.id, "wave_id": p["wave_id"]},
            tz=event.timezone,
        )


@outbox.subscribe("chat.message_created")
async def message_created(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        name = (await _names(session, event.id, [p["from_user"]]))[p["from_user"]]
        await notify(
            session,
            p["to_user"],
            "message",
            name,
            "",  # the preview is filled in from the encrypted message when the push is sent
            data={"conversation_id": p["conversation_id"]},
            collapse=f"conv:{p['conversation_id']}",
            tz=event.timezone,
            store=False,
            message_id=p["message_id"],
        )


@outbox.subscribe("chat.meet_reminder")
async def meet_reminder(p: dict[str, Any]) -> None:
    a, b = p["user_ids"]
    async with UnitOfWork() as session:
        names = await _names(session, p["event_id"], [a, b])
        for me, peer in ((a, b), (b, a)):
            await notify(
                session,
                me,
                "meet",
                "Meeting soon",
                f"Meeting {names[peer]} at {p['meeting_point']} in 10 min",
                data={"conversation_id": p["conversation_id"]},
            )


@outbox.subscribe("events.application_decided")
async def application_decided(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        approved = p["status"] == "approved"
        await notify(
            session,
            p["user_id"],
            "event",
            event.name,
            f"You're in! {event.name}" if approved else "Update on your application",
            data={"event_id": event.id},
            tz=event.timezone,
        )


@outbox.subscribe("events.announcement_created")
async def announcement(p: dict[str, Any]) -> None:
    await jobs.enqueue(
        "notifications.announce",
        p["event_id"],
        p["announcement_id"],
        p["event_name"],
        p["body"],
        job_id=f"ann:{p['announcement_id']}",
    )


@outbox.subscribe("connections.wrapup_ready")
async def wrapup_ready(p: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        event = await events.get_info(session, p["event_id"])
        await notify(
            session,
            p["user_id"],
            "wrapup",
            "Your wrap-up",
            f"Your {event.name} wrap-up is ready",
            data={"event_id": event.id},
            collapse=f"wrapup:{event.id}",
            tz=event.timezone,
        )


@outbox.subscribe("safety.report_actioned")
async def warned(p: dict[str, Any]) -> None:
    if p["action"] != "warn":
        return
    async with UnitOfWork() as session:
        await notify(
            session,
            p["subject_id"],
            "safety",
            "A note from the team",
            "Someone reported your behaviour. Please keep it professional.",
        )
