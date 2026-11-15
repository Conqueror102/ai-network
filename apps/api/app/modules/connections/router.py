from typing import Annotated

from fastapi import APIRouter, Query

from app.core import ratelimit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.core.db.pagination import Page, clamp_limit
from app.modules.connections import schemas, service

router = APIRouter(tags=["connections"])


@router.post("/exchange/token", response_model=schemas.TokenOut)
async def exchange_token(
    body: schemas.TokenIn, user: CurrentUser, session: DbSession
) -> schemas.TokenOut:
    await ratelimit.hit("xchg_token", user.user_id, limit=30, window_s=60)
    payload, ttl = await service.issue_token(session, user.user_id, body.event_id)
    return schemas.TokenOut(qr_payload=payload, ttl_s=ttl)


@router.post("/exchange/scan", response_model=schemas.PendingExchangeOut)
async def exchange_scan(
    body: schemas.ScanIn, user: CurrentUser, session: DbSession
) -> schemas.PendingExchangeOut:
    await ratelimit.hit("xchg_scan", user.user_id, limit=20, window_s=60)  # no token guessing
    return await service.scan(session, user.user_id, body.qr_payload, body.event_id)


@router.get("/exchange/pending", response_model=schemas.PendingExchangeOut | None)
async def exchange_pending(
    user: CurrentUser, session: DbSession
) -> schemas.PendingExchangeOut | None:
    """The QR owner polls this (or gets `exchange.pending` over WS) to find the confirm."""
    return await service.pending(session, user.user_id)


@router.post("/exchange/{confirm_id}/confirm", response_model=schemas.ConfirmOut)
async def exchange_confirm(
    confirm_id: str, user: CurrentUser, session: DbSession
) -> schemas.ConfirmOut:
    return await service.confirm(session, user.user_id, confirm_id)


@router.get("/connections", response_model=Page[schemas.ConnectionOut])
async def list_connections(
    user: CurrentUser,
    session: DbSession,
    event_id: Annotated[str | None, Query(max_length=40)] = None,
    cursor: Annotated[str | None, Query(max_length=400)] = None,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> Page[schemas.ConnectionOut]:
    items, nxt = await service.list_mine(
        session, user.user_id, event_id, cursor, clamp_limit(limit)
    )
    return Page(items=items, next_cursor=nxt)


@router.patch("/connections/{connection_id}", response_model=schemas.ConnectionOut)
async def patch_connection(
    connection_id: str, body: schemas.NotesIn, user: CurrentUser, session: DbSession
) -> schemas.ConnectionOut:
    return await service.set_notes(session, user.user_id, connection_id, body.notes)
