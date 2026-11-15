import contextlib

import structlog
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.auth import CurrentUser, is_revoked
from app.core.db.uow import UnitOfWork
from app.core.errors import RateLimited
from app.core.redis import get_redis
from app.core.security.jwt import verify_access_token
from app.modules.events import public as events
from app.modules.organizers import public as organizers
from app.modules.realtime import service
from app.modules.realtime.public import event_channel, user_channel

log = structlog.get_logger()
router = APIRouter(tags=["realtime"])
ws_router = APIRouter()


class TicketOut(BaseModel):
    ticket: str
    ttl_s: int


@router.post("/ws/ticket", response_model=TicketOut)
async def ws_ticket(request: Request, user: CurrentUser) -> TicketOut:
    token = request.headers["authorization"].partition(" ")[2]
    exp = int(verify_access_token(token)["exp"])
    return TicketOut(
        ticket=await service.issue_ticket(user.user_id, exp), ttl_s=service.TICKET_TTL_S
    )


async def channels_for(user_id: str, stats_event_id: str | None) -> list[str]:
    """`user:{id}` always; `event:{id}:attendee` for live events the user is checked
    into; `event:{id}:stats` only for staff of that event's organizer."""
    out = [user_channel(user_id)]
    async with UnitOfWork() as session:
        for event_id in await events.live_checked_in_event_ids(session, user_id):
            out.append(event_channel(event_id, "attendee"))
        if stats_event_id:
            with contextlib.suppress(Exception):
                info = await events.get_info(session, stats_event_id)
                if await organizers.role_of(session, info.organizer_id, user_id):
                    out.append(event_channel(stats_event_id, "stats"))
    return out


@ws_router.websocket("/ws")
async def ws(websocket: WebSocket, ticket: str = "", stats: str | None = None) -> None:
    redeemed = await service.redeem_ticket(ticket)
    if redeemed is None or await is_revoked(redeemed[0]):
        await websocket.close(code=service.CLOSE_BAD_TICKET)
        return
    user_id, expires_at = redeemed
    try:
        await service.acquire_slot(user_id)
    except RateLimited:
        await websocket.close(code=service.CLOSE_TOO_MANY)
        return
    await websocket.accept()
    pubsub = get_redis().pubsub()
    code = 1000
    try:
        await pubsub.subscribe(*await channels_for(user_id, stats))
        code = await service.pump(
            pubsub,
            websocket.send_text,
            websocket.receive_text,
            user_id=user_id,
            expires_at=expires_at,
        )
    except WebSocketDisconnect:
        pass
    finally:
        with contextlib.suppress(Exception):
            await pubsub.aclose()  # type: ignore[no-untyped-call]
        await service.release_slot(user_id)
        with contextlib.suppress(Exception):
            await websocket.close(code=code)
