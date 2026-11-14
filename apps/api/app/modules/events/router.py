from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from app.core import ratelimit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.core.errors import NotFound
from app.modules.events import schemas, service
from app.modules.events.deps import CheckedIn, OrgStaff
from app.modules.organizers import public as organizers

router = APIRouter(tags=["events"])
Cursor = Annotated[str | None, Query(max_length=400)]
Limit = Annotated[int | None, Query(ge=1, le=100)]


# --- public / attendee -----------------------------------------------------------------


@router.get("/events", response_model=Page[schemas.EventOut])
async def discover(
    request: Request,
    session: DbSession,
    city: Annotated[str | None, Query(max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[schemas.EventOut]:
    await ratelimit.hit("ip_unauth", ratelimit.client_ip(request), limit=20, window_s=60)
    rows, nxt = await service.discover(
        session, city=city, q=q, cursor=cursor, limit=clamp_limit(limit)
    )
    return Page(items=[service.to_out(e, show_address=False) for e in rows], next_cursor=nxt)


@router.get("/events/{event_id}", response_model=schemas.EventOut)
async def event_detail(event_id: str, user: CurrentUser, session: DbSession) -> schemas.EventOut:
    event = await service.get_event(session, event_id)
    role = await organizers.role_of(session, event.organizer_id, user.user_id)
    if role is None and not service.visible_to_attendees(event):
        raise NotFound
    application = await service.application_status(session, event_id, user.user_id)
    checked_in = await service.is_checked_in(session, event_id, user.user_id)
    return service.to_out(
        event,
        show_address=role is not None or application == "approved",
        application=application,
        checked_in=checked_in,
    )


@router.post("/events/{event_id}/apply", response_model=schemas.ApplyOut)
async def apply(event_id: str, user: CurrentUser, session: DbSession) -> schemas.ApplyOut:
    event = await service.get_event(session, event_id)
    return schemas.ApplyOut(status=await service.apply(session, event, user.user_id))


@router.post("/events/{event_id}/checkin", response_model=schemas.CheckinOut)
async def checkin(
    event_id: str, body: schemas.CheckinIn, user: CurrentUser, session: DbSession
) -> schemas.CheckinOut:
    await ratelimit.hit("checkin", user.user_id, limit=10, window_s=60)
    event = await service.get_event(session, event_id)
    await service.check_in(session, event, user.user_id, body.qr_token)
    return schemas.CheckinOut()


@router.get("/events/{event_id}/announcements", response_model=Page[schemas.AnnouncementOut])
async def announcements(
    ctx: CheckedIn, session: DbSession, cursor: Cursor = None, limit: Limit = None
) -> Page[schemas.AnnouncementOut]:
    items, nxt = await service.list_announcements(session, ctx.event.id, cursor, clamp_limit(limit))
    return Page(items=items, next_cursor=nxt)


# --- organizer -------------------------------------------------------------------------


@router.post("/organizers/{organizer_id}/events", response_model=schemas.EventOut, status_code=201)
async def create_event(
    organizer_id: str, body: schemas.EventCreateIn, user: CurrentUser, session: DbSession
) -> schemas.EventOut:
    await organizers.require_role(session, organizer_id, user.user_id, "staff")
    return service.to_out(await service.create(session, organizer_id, body), show_address=True)


@router.get("/organizers/{organizer_id}/events", response_model=Page[schemas.EventOut])
async def organizer_events(
    organizer_id: str,
    user: CurrentUser,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[schemas.EventOut]:
    await organizers.require_role(session, organizer_id, user.user_id, "staff")
    rows, nxt = await service.list_for_organizer(session, organizer_id, cursor, clamp_limit(limit))
    return Page(items=[service.to_out(e, show_address=True) for e in rows], next_cursor=nxt)


@router.patch("/events/{event_id}", response_model=schemas.EventOut)
async def patch_event(
    body: schemas.EventPatchIn, ctx: OrgStaff, session: DbSession
) -> schemas.EventOut:
    return service.to_out(await service.update(session, ctx.event, body), show_address=True)


@router.post("/events/{event_id}/status", response_model=schemas.EventOut)
async def set_status(body: schemas.StatusIn, ctx: OrgStaff, session: DbSession) -> schemas.EventOut:
    return service.to_out(
        await service.set_status(session, ctx.event, body.status), show_address=True
    )


@router.get("/events/{event_id}/door-qr", response_model=schemas.DoorQrOut)
async def door_qr(ctx: OrgStaff) -> schemas.DoorQrOut:
    token, ttl, static = service.door_qr(ctx.event)
    return schemas.DoorQrOut(qr_token=token, expires_in_s=ttl, static_qr_token=static)


@router.get("/events/{event_id}/applications", response_model=Page[schemas.ApplicationOut])
async def applications(
    ctx: OrgStaff,
    session: DbSession,
    status: Annotated[str | None, Query(pattern="^(pending|approved|rejected)$")] = None,
    cursor: Cursor = None,
    limit: Limit = None,
) -> Page[schemas.ApplicationOut]:
    items, nxt = await service.list_applications(
        session, ctx.event.id, status, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.post(
    "/events/{event_id}/applications/{application_id}/decide", response_model=schemas.ApplyOut
)
async def decide(
    application_id: str, body: schemas.DecideIn, ctx: OrgStaff, session: DbSession
) -> schemas.ApplyOut:
    app = await service.decide_application(
        session, application_id, ctx.event.id, body.approve, ctx.user.user_id
    )
    return schemas.ApplyOut(status=app.status)


@router.get("/events/{event_id}/stats/live", response_model=schemas.LiveStatsOut)
async def stats_live(ctx: OrgStaff, session: DbSession) -> schemas.LiveStatsOut:
    return await service.live_stats(session, ctx.event)


@router.post(
    "/events/{event_id}/announcements", response_model=schemas.AnnouncementOut, status_code=201
)
async def announce(
    body: schemas.AnnouncementIn, ctx: OrgStaff, session: DbSession
) -> schemas.AnnouncementOut:
    ann = await service.announce(session, ctx.event, ctx.user.user_id, body.body)
    return schemas.AnnouncementOut(
        id=ann.id, event_id=ann.event_id, body=ann.body, created_at=ann.created_at
    )


@router.delete("/events/{event_id}", status_code=204, include_in_schema=False)
async def _no_delete(event_id: str) -> Response:
    """Events are cancelled, never deleted (history, analytics, connections depend on them)."""
    return Response(status_code=405)
