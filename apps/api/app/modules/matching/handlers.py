from typing import Any

from app.core import jobs, outbox
from app.core.db.uow import UnitOfWork
from app.modules.matching import service
from app.modules.matching.jobs import job_id


@outbox.subscribe("profiles.embedded")
async def on_profile_embedded(payload: dict[str, Any]) -> None:
    await jobs.enqueue(
        "matching.compute_for_user",
        payload["event_id"],
        payload["user_id"],
        job_id=job_id(payload["event_id"], payload["user_id"]),
    )


@outbox.subscribe("events.checked_in")
async def on_checked_in(payload: dict[str, Any]) -> None:
    """A returning attendee (day two) gets a fresh feed. First-timers have no profile
    yet, so this is a no-op for them until `profiles.embedded` fires."""
    await jobs.enqueue(
        "matching.compute_for_user",
        payload["event_id"],
        payload["user_id"],
        job_id=job_id(payload["event_id"], payload["user_id"]),
    )


@outbox.subscribe("identity.user_deleted")
async def on_user_deleted(payload: dict[str, Any]) -> None:
    async with UnitOfWork() as session:
        await service.forget_user(session, payload["user_id"])
