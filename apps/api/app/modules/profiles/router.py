from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core import ratelimit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.events import public as events
from app.modules.events.public import CheckedIn
from app.modules.profiles import schemas, service

router = APIRouter(tags=["profiles"])


@router.get("/events/{event_id}/room", response_model=schemas.RoomOut)
async def room(ctx: CheckedIn, session: DbSession) -> schemas.RoomOut:
    profile = await service.get_profile(session, ctx.event.id, ctx.user.user_id)
    goals = await service.list_goals(session, profile.id) if profile else []
    return schemas.RoomOut(
        event_id=ctx.event.id,
        event_name=ctx.event.name,
        status=ctx.event.status,
        checked_in_count=await events.checked_in_count(session, ctx.event.id),
        meeting_points=ctx.event.meeting_points,
        my_profile=await service.my_profile_out(session, profile) if profile else None,
        goals=[service.goal_out(g) for g in goals],
    )


@router.put("/events/{event_id}/profile", response_model=schemas.MyEventProfileOut)
async def put_profile(
    body: schemas.EventProfileIn, ctx: CheckedIn, session: DbSession
) -> schemas.MyEventProfileOut:
    profile = await service.upsert_profile(session, ctx.event.id, ctx.user.user_id, body)
    return await service.my_profile_out(session, profile)


@router.get("/events/{event_id}/profiles/{user_id}", response_model=schemas.EventCardOut)
async def view_profile(user_id: str, ctx: CheckedIn, session: DbSession) -> schemas.EventCardOut:
    return await service.view_profile(session, ctx.event.id, ctx.user.user_id, user_id)


@router.get("/events/{event_id}/directory", response_model=Page[schemas.EventCardOut])
async def directory(
    ctx: CheckedIn,
    session: DbSession,
    q: Annotated[str | None, Query(max_length=60)] = None,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.EventCardOut]:
    await ratelimit.hit("directory", ctx.user.user_id, limit=30, window_s=60)  # anti-scrape
    items, nxt = await service.directory(
        session, ctx.event.id, ctx.user.user_id, q, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.post("/events/{event_id}/goals/parse", response_model=schemas.GoalParseOut)
async def parse_goal(body: schemas.GoalParseIn, ctx: CheckedIn) -> schemas.GoalParseOut:
    await ratelimit.hit("goal_parse", ctx.user.user_id, limit=20, window_s=3600)
    draft = await service.parse_goal(body.text, ctx.user.user_id, ctx.event.id)
    return schemas.GoalParseOut(goal=draft, manual=draft is None)


@router.get("/events/{event_id}/goals", response_model=list[schemas.GoalOut])
async def my_goals(ctx: CheckedIn, session: DbSession) -> list[schemas.GoalOut]:
    profile = await service.require_profile(session, ctx.event.id, ctx.user.user_id)
    return [service.goal_out(g) for g in await service.list_goals(session, profile.id)]


@router.post("/events/{event_id}/goals", response_model=schemas.GoalOut, status_code=201)
async def create_goal(body: schemas.GoalIn, ctx: CheckedIn, session: DbSession) -> schemas.GoalOut:
    profile = await service.require_profile(session, ctx.event.id, ctx.user.user_id)
    return service.goal_out(await service.create_goal(session, profile, body))


@router.patch("/goals/{goal_id}", response_model=schemas.GoalOut)
async def patch_goal(
    goal_id: str, body: schemas.GoalPatchIn, user: CurrentUser, session: DbSession
) -> schemas.GoalOut:
    return service.goal_out(await service.update_goal(session, goal_id, user.user_id, body))


@router.delete("/goals/{goal_id}", status_code=204)
async def delete_goal(goal_id: str, user: CurrentUser, session: DbSession) -> Response:
    await service.archive_goal(session, goal_id, user.user_id)
    return Response(status_code=204)
