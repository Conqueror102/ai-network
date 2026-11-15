from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.events import public as events
from app.modules.events.public import CheckedIn
from app.modules.waves import schemas, service

router = APIRouter(tags=["waves"])


@router.post("/events/{event_id}/waves", response_model=schemas.SentWaveOut, status_code=201)
async def send_wave(
    body: schemas.WaveIn, ctx: CheckedIn, session: DbSession
) -> schemas.SentWaveOut:
    info = await events.get_info(session, ctx.event.id)
    wave = await service.send(session, info, ctx.user.user_id, ctx.user.premium, body)
    return (await service.sent_view(session, [wave]))[0]


@router.get("/events/{event_id}/waves/inbox", response_model=Page[schemas.InboxWaveOut])
async def inbox(
    ctx: CheckedIn,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.InboxWaveOut]:
    items, nxt = await service.list_inbox(
        session, ctx.event.id, ctx.user.user_id, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.get("/events/{event_id}/waves/sent", response_model=Page[schemas.SentWaveOut])
async def sent(
    ctx: CheckedIn,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.SentWaveOut]:
    items, nxt = await service.list_sent(
        session, ctx.event.id, ctx.user.user_id, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.post("/waves/{wave_id}/respond", response_model=None)
async def respond(
    wave_id: str, body: schemas.RespondIn, user: CurrentUser, session: DbSession
) -> schemas.RespondOut | Response:
    cid = await service.respond(session, user.user_id, wave_id, body.action)
    if cid:
        return schemas.RespondOut(conversation_id=cid)
    return Response(status_code=204)
