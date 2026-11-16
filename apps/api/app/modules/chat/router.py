from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response
from pydantic import AwareDatetime

from app.core import idempotency, ratelimit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.chat import schemas, service
from app.modules.events import public as events

router = APIRouter(tags=["chat"])


@router.get("/conversations", response_model=Page[schemas.ConversationOut])
async def conversations(
    user: CurrentUser,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.ConversationOut]:
    items, nxt = await service.list_conversations(session, user.user_id, cursor, clamp_limit(limit))
    return Page(items=items, next_cursor=nxt)


@router.get("/conversations/{conversation_id}/messages", response_model=Page[schemas.MessageOut])
async def messages(
    conversation_id: str,
    user: CurrentUser,
    session: DbSession,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.MessageOut]:
    items, nxt = await service.list_messages(
        session, conversation_id, user.user_id, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.post(
    "/conversations/{conversation_id}/messages", response_model=schemas.MessageOut, status_code=201
)
async def send(
    conversation_id: str,
    body: schemas.MessageIn,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: Annotated[str | None, Header(max_length=128)] = None,
) -> Any:
    fingerprint = {"c": conversation_id, **body.model_dump()}
    replay = await idempotency.lookup(user.user_id, idempotency_key, fingerprint)
    if replay is not None:
        return replay
    await ratelimit.hit("messages", user.user_id, limit=20, window_s=60)
    out = await service.send_message(session, conversation_id, user.user_id, body)
    await idempotency.store(user.user_id, idempotency_key, fingerprint, out.model_dump(mode="json"))
    return out


@router.post("/conversations/{conversation_id}/read", status_code=204)
async def read(
    conversation_id: str, body: schemas.ReadIn, user: CurrentUser, session: DbSession
) -> Response:
    await service.mark_read(session, conversation_id, user.user_id, body.last_message_id)
    return Response(status_code=204)


@router.post("/conversations/{conversation_id}/meet", response_model=schemas.MessageOut)
async def meet(
    conversation_id: str, body: schemas.MeetIn, user: CurrentUser, session: DbSession
) -> schemas.MessageOut:
    await ratelimit.hit("meet", user.user_id, limit=10, window_s=600)
    if body.accept_message_id:
        return await service.accept_meet(
            session, conversation_id, user.user_id, body.accept_message_id, body.spot_me
        )
    return await service.propose_meet(session, conversation_id, user.user_id, body)


@router.post(
    "/conversations/{conversation_id}/meet/{message_id}/status", response_model=schemas.MessageOut
)
async def meet_status(
    conversation_id: str,
    message_id: str,
    body: schemas.MeetStatusIn,
    user: CurrentUser,
    session: DbSession,
) -> schemas.MessageOut:
    """Set "how to spot me" or tap "I'm here" on a meet-up. Returns the meet-up card."""
    await ratelimit.hit("meet_status", user.user_id, limit=20, window_s=600)
    return await service.meet_status(session, conversation_id, user.user_id, message_id, body)


@router.get("/events/{event_id}/meet-spots", response_model=list[schemas.MeetSpotOut])
async def meet_spots(
    ctx: events.CheckedIn, session: DbSession, at: AwareDatetime | None = None
) -> list[schemas.MeetSpotOut]:
    """The numbered places to meet, how busy each is around `at`, and the one to pick."""
    return await service.meet_spots(session, ctx.event.id, at)
