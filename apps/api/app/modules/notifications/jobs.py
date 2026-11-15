from typing import Any

import structlog

from app.adapters import factory
from app.adapters.email.port import EmailSendError
from app.adapters.push.port import PushGone, PushSendError, PushTarget
from app.core import jobs
from app.core.db.uow import UnitOfWork
from app.modules.chat import public as chat
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.notifications import service

log = structlog.get_logger()
EMAIL_FALLBACK = {"wave_accepted", "meet", "event", "wrapup"}
CHUNK = 200


@jobs.job("notifications.push", max_tries=4, timeout_s=30)
async def push(user_id: str, n: dict[str, Any]) -> None:
    """Deliver one push to every device of a user. Dead subscriptions are deleted.
    With no working device, important categories fall back to email."""
    async with UnitOfWork() as session:
        if not await service.push_enabled(session, user_id, n["category"]):
            return  # muted while the push was waiting out quiet hours
        body = n["body"]
        if n.get("message_id"):
            preview = await chat.preview(session, n["message_id"])
            if preview is None:
                return
            body = f"{n['body']}{preview[1]}"
        payload = {
            "title": n["title"],
            "body": body,
            "data": n["data"],
            "tag": n.get("collapse"),
            "category": n["category"],
        }
        delivered = 0
        for sub in await identity.push_subscriptions(session, user_id):
            try:
                await factory.push().send(
                    PushTarget(sub.id, sub.endpoint, sub.p256dh, sub.auth), payload
                )
                delivered += 1
            except PushGone:
                await identity.delete_push_subscription(session, sub.id)
            except PushSendError:
                log.warning("push_failed", user_id=user_id, category=n["category"])
        if delivered == 0 and n["category"] in EMAIL_FALLBACK:
            email, _ = await identity.private_contact(session, user_id)
            if email:
                try:
                    await factory.email().send(
                        to=email, subject=n["title"], html=f"<p>{_escape(body)}</p>"
                    )
                except EmailSendError:
                    log.warning("email_fallback_failed", user_id=user_id)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


@jobs.job("notifications.announce", timeout_s=300)
async def announce(event_id: str, announcement_id: str, event_name: str, body: str) -> None:
    """Fan an organizer announcement out to everyone checked in (01 §11.2)."""
    async with UnitOfWork() as session:
        info = await events.get_info(session, event_id)
        user_ids = await events.checked_in_user_ids(session, event_id)
        for start in range(0, len(user_ids), CHUNK):
            for user_id in user_ids[start : start + CHUNK]:
                await service.notify(
                    session,
                    user_id,
                    "event",
                    event_name,
                    body[:80],
                    data={"event_id": event_id, "announcement_id": announcement_id},
                    collapse=f"ann:{event_id}",
                    tz=info.timezone,
                )
            await session.commit()
