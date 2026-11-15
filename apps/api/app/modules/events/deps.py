"""Authorization dependencies for event-scoped routes (08 §2). Never inline in handlers."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.core.auth import CurrentUser, Principal
from app.core.db.engine import DbSession
from app.core.errors import Forbidden, NotFound
from app.modules.events import service
from app.modules.events.models import Event
from app.modules.organizers import public as organizers


@dataclass
class EventCtx:
    event: Event
    user: Principal
    role: str | None = None  # organizer role when resolved through require_org_*


async def require_checkin(event_id: str, user: CurrentUser, session: DbSession) -> EventCtx:
    """The caller is checked into this event. Everything in the event room needs it."""
    event = await session.get(Event, event_id)
    if event is None or not service.visible_to_attendees(event):
        raise NotFound
    if not await service.is_checked_in(session, event_id, user.user_id):
        raise Forbidden("Check in at the event to unlock this", code="checkin_required")
    return EventCtx(event, user)


async def _org(
    event_id: str, user: Principal, session: DbSession, minimum: organizers.Role
) -> EventCtx:
    event = await session.get(Event, event_id)
    if event is None:
        raise NotFound
    role = await organizers.require_role(session, event.organizer_id, user.user_id, minimum)
    return EventCtx(event, user, role)


async def require_org_staff(event_id: str, user: CurrentUser, session: DbSession) -> EventCtx:
    return await _org(event_id, user, session, "staff")


async def require_org_owner(event_id: str, user: CurrentUser, session: DbSession) -> EventCtx:
    return await _org(event_id, user, session, "owner")


CheckedIn = Annotated[EventCtx, Depends(require_checkin)]
OrgStaff = Annotated[EventCtx, Depends(require_org_staff)]
OrgOwner = Annotated[EventCtx, Depends(require_org_owner)]
