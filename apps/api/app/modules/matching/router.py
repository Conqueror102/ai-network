from dataclasses import asdict

from fastapi import APIRouter, Response

from app.core import jobs
from app.core.audit import Audit
from app.core.auth import StaffUser
from app.core.db.engine import DbSession
from app.modules.events.public import CheckedIn
from app.modules.matching import schemas, service
from app.modules.matching.jobs import FANOUT_DEBOUNCE_S, job_id
from app.modules.matching.models import MatchingConfig

router = APIRouter(tags=["matching"])


@router.get("/events/{event_id}/matches", response_model=schemas.FeedOut)
async def matches(ctx: CheckedIn, session: DbSession) -> schemas.FeedOut:
    feed, computed_now = await service.feed(session, ctx.event.id, ctx.user.user_id)
    if computed_now:
        await jobs.enqueue(
            "matching.explain",
            ctx.event.id,
            ctx.user.user_id,
            job_id=f"why:{ctx.event.id}:{ctx.user.user_id}",
        )
    return feed


@router.post("/events/{event_id}/matches/{user_id}/skip", status_code=204)
async def skip(user_id: str, ctx: CheckedIn, session: DbSession) -> Response:
    await service.skip(session, ctx.event.id, ctx.user.user_id, user_id)
    await jobs.enqueue(  # refill the freed slot
        "matching.compute_for_user",
        ctx.event.id,
        ctx.user.user_id,
        False,
        job_id=job_id(ctx.event.id, ctx.user.user_id),
        defer_s=FANOUT_DEBOUNCE_S,
    )
    return Response(status_code=204)


@router.get("/internal/matching/config", response_model=schemas.ConfigOut)
async def get_config(_: StaffUser, session: DbSession) -> schemas.ConfigOut:
    cfg = await service.load_config(session, fresh=True)
    row = await session.get(MatchingConfig, "default")
    return schemas.ConfigOut(values=asdict(cfg), overrides=row.values if row else {})


@router.put("/internal/matching/config", response_model=schemas.ConfigOut)
async def put_config(
    body: schemas.ConfigIn, staff: StaffUser, session: DbSession, audit: Audit
) -> schemas.ConfigOut:
    audit.log(
        "matching.config_set", "matching_config", "default", meta={"keys": sorted(body.values)}
    )
    cfg, overrides = await service.set_config(session, body.values, staff.user_id)
    return schemas.ConfigOut(values=asdict(cfg), overrides=overrides)
