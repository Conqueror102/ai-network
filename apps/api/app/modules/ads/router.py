from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.core import ratelimit
from app.core.auth import StaffUser
from app.core.db.engine import DbSession
from app.modules.ads import schemas, service
from app.modules.events.public import CheckedIn, OrgStaff

router = APIRouter(tags=["ads"])


class StatusIn(BaseModel):
    status: Literal["active", "paused"]


@router.get("/events/{event_id}/sponsored", response_model=schemas.SponsoredOut)
async def sponsored(ctx: CheckedIn, session: DbSession) -> schemas.SponsoredOut:
    return schemas.SponsoredOut(
        tile=await service.tile_for(session, ctx.event.id, ctx.user.user_id)
    )


@router.post("/events/{event_id}/sponsored/{placement_id}/tap", status_code=204)
async def tap(placement_id: str, ctx: CheckedIn, session: DbSession) -> Response:
    await ratelimit.hit("ad_tap", ctx.user.user_id, limit=20, window_s=3600)  # no click farms
    await service.tap(session, ctx.event.id, placement_id)
    return Response(status_code=204)


@router.post("/events/{event_id}/ads", response_model=schemas.PlacementOut, status_code=201)
async def create(
    body: schemas.PlacementIn, ctx: OrgStaff, session: DbSession
) -> schemas.PlacementOut:
    return service.out(await service.create(session, ctx.event.id, ctx.user.user_id, body))


@router.get("/events/{event_id}/ads", response_model=list[schemas.PlacementOut])
async def list_ads(ctx: OrgStaff, session: DbSession) -> list[schemas.PlacementOut]:
    return [service.out(p) for p in await service.list_for_event(session, ctx.event.id)]


@router.post("/events/{event_id}/ads/{placement_id}/status", status_code=204)
async def set_status(
    placement_id: str, body: StatusIn, ctx: OrgStaff, session: DbSession
) -> Response:
    await service.set_status(session, ctx.event.id, placement_id, body.status)
    return Response(status_code=204)


@router.get("/events/{event_id}/sponsors/{sponsor_id}/report", response_model=schemas.ReportOut)
async def report(sponsor_id: str, ctx: OrgStaff, session: DbSession) -> schemas.ReportOut:
    return await service.report(session, ctx.event.id, sponsor_id)


@router.post("/internal/ads/{placement_id}/release", status_code=204)
async def release(placement_id: str, _: StaffUser, session: DbSession) -> Response:
    await service.release_held(session, placement_id)
    return Response(status_code=204)
