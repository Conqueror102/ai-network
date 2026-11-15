from fastapi import APIRouter, Response

from app.core.db.engine import DbSession
from app.modules.events.public import OrgStaff
from app.modules.sponsors import schemas, service

router = APIRouter(tags=["sponsors"])


@router.post("/events/{event_id}/sponsors", response_model=schemas.SponsorOut, status_code=201)
async def create(body: schemas.SponsorIn, ctx: OrgStaff, session: DbSession) -> schemas.SponsorOut:
    return service.out(await service.create(session, ctx.event.id, ctx.user.user_id, body))


@router.get("/events/{event_id}/sponsors", response_model=list[schemas.SponsorOut])
async def list_sponsors(ctx: OrgStaff, session: DbSession) -> list[schemas.SponsorOut]:
    return [service.out(s) for s in await service.list_for_event(session, ctx.event.id)]


@router.delete("/events/{event_id}/sponsors/{sponsor_id}", status_code=204)
async def archive(sponsor_id: str, ctx: OrgStaff, session: DbSession) -> Response:
    await service.archive(session, ctx.event.id, sponsor_id)
    return Response(status_code=204)
