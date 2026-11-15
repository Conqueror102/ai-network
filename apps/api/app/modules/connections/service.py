"""Tap-to-exchange and the personal CRM (01 §8.7, 04 §4.4).

The handshake lives in Redis (short-lived, nothing durable until both confirm):
  xchg:tok:<token>      -> "<owner>|<event>"   60 s QR token, single use
  xchg:mine:<user>      -> token               one live token per user
  xchg:cfm:<confirm_id> -> hash {a, b, event_id, ok_a, ok_b, done}   10 min
  xchg:pending:<user>   -> confirm_id          so the QR owner can find the confirm
"""

import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import clock, outbox
from app.core.db.pagination import decode_cursor, paginate
from app.core.errors import Forbidden, NotFound
from app.core.ids import new_id
from app.core.redis import get_redis, key
from app.core.security.hashing import random_token
from app.modules.connections import errors
from app.modules.connections.models import Connection
from app.modules.connections.schemas import (
    ConfirmOut,
    ConnectionOut,
    PendingExchangeOut,
    SharedContact,
)
from app.modules.events import public as events
from app.modules.identity import public as identity
from app.modules.profiles import public as profiles
from app.modules.safety import public as safety

TOKEN_TTL_S = 60
TOKEN_GRACE_S = 15  # the scan may land just after the QR rotated
CONFIRM_TTL_S = 600

# Sets my flag; returns 1 = waiting for the other side, 2 = both confirmed (or already done).
_CONFIRM_LUA = """
if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
redis.call('HSET', KEYS[1], ARGV[1], '1')
if redis.call('HGET', KEYS[1], 'ok_a') == '1' and redis.call('HGET', KEYS[1], 'ok_b') == '1' then
  redis.call('HSET', KEYS[1], 'done', '1')
  return 2
end
return 1
"""


async def _require_checkin(session: AsyncSession, event_id: str, user_id: str) -> None:
    if not await events.is_checked_in(session, event_id, user_id):
        raise Forbidden("Check in at the event to unlock this", code="checkin_required")


async def issue_token(session: AsyncSession, user_id: str, event_id: str) -> tuple[str, int]:
    await _require_checkin(session, event_id, user_id)
    r = get_redis()
    mine = key("xchg", "mine", user_id)
    old = await r.get(mine)
    if old:
        await r.delete(key("xchg", "tok", old))
    token = random_token(18)
    ttl = TOKEN_TTL_S + TOKEN_GRACE_S
    await r.set(key("xchg", "tok", token), f"{user_id}|{event_id}", ex=ttl)
    await r.set(mine, token, ex=ttl)
    return f"x.{token}", TOKEN_TTL_S


async def scan(
    session: AsyncSession, scanner_id: str, qr_payload: str, event_id: str
) -> PendingExchangeOut:
    await _require_checkin(session, event_id, scanner_id)
    r = get_redis()
    raw = await r.getdel(key("xchg", "tok", qr_payload.removeprefix("x."))) if qr_payload else None
    if not raw:
        raise errors.ExchangeTokenInvalid
    owner_id, _, token_event = raw.partition("|")
    if owner_id == scanner_id:
        raise errors.ExchangeSelf
    # A blocked pair or a different event looks exactly like an expired code.
    if token_event != event_id or await safety.is_blocked_pair(session, owner_id, scanner_id):
        raise errors.ExchangeTokenInvalid
    owner = await identity.get_card(session, owner_id)
    if not owner.active:
        raise errors.ExchangeTokenInvalid
    confirm_id = new_id("xcf")
    ck = key("xchg", "cfm", confirm_id)
    await r.hset(  # type: ignore[misc]
        ck,
        mapping={"a": owner_id, "b": scanner_id, "event_id": event_id, "ok_a": "0", "ok_b": "0"},
    )
    await r.expire(ck, CONFIRM_TTL_S)
    for uid in (owner_id, scanner_id):
        await r.set(key("xchg", "pending", uid), confirm_id, ex=CONFIRM_TTL_S)
    outbox.emit(
        session,
        "connections.exchange_scanned",
        {"confirm_id": confirm_id, "event_id": event_id, "user_id": owner_id, "by": scanner_id},
    )
    await session.commit()
    cards = await profiles.get_event_cards(session, event_id, [owner_id])
    return PendingExchangeOut(
        confirm_id=confirm_id,
        event_id=event_id,
        peer_card=cards[owner_id],
        i_confirmed=False,
        expires_in_s=CONFIRM_TTL_S,
    )


async def _load_confirm(confirm_id: str, me: str) -> tuple[dict[str, str], str]:
    """Returns (state, my side "a"|"b"). 404 for strangers as well as expired ids."""
    state: dict[str, str] = await get_redis().hgetall(key("xchg", "cfm", confirm_id))  # type: ignore[misc]
    if not state or me not in (state.get("a"), state.get("b")):
        raise errors.ExchangeNotFound
    return state, "a" if state["a"] == me else "b"


async def pending(session: AsyncSession, me: str) -> PendingExchangeOut | None:
    r = get_redis()
    confirm_id = await r.get(key("xchg", "pending", me))
    if not confirm_id:
        return None
    try:
        state, side = await _load_confirm(confirm_id, me)
    except errors.ExchangeNotFound:
        return None
    if state.get("done") == "1":
        return None
    peer = state["b" if side == "a" else "a"]
    if await safety.is_blocked_pair(session, me, peer):
        return None
    cards = await profiles.get_event_cards(session, state["event_id"], [peer])
    ttl = await r.ttl(key("xchg", "cfm", confirm_id))
    return PendingExchangeOut(
        confirm_id=confirm_id,
        event_id=state["event_id"],
        peer_card=cards[peer],
        i_confirmed=state[f"ok_{side}"] == "1",
        expires_in_s=max(0, int(ttl)),
    )


async def _upsert(
    session: AsyncSession,
    *,
    user_id: str,
    peer_id: str,
    event_id: str,
    met: bool,
    shared: dict[str, Any] | None,
) -> None:
    now = clock.now()
    stmt = insert(Connection).values(
        id=new_id("con"),
        user_id=user_id,
        peer_id=peer_id,
        event_id=event_id,
        met_confirmed_at=now if met else None,
        shared=json.dumps(shared) if shared is not None else None,
    )
    if met:
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "peer_id", "event_id"],
            set_={
                "met_confirmed_at": func.coalesce(Connection.met_confirmed_at, now),
                "shared": stmt.excluded.shared,
                "updated_at": now,
            },
        )
    else:
        stmt = stmt.on_conflict_do_nothing()
    await session.execute(stmt)


async def confirm(session: AsyncSession, me: str, confirm_id: str) -> ConfirmOut:
    state, side = await _load_confirm(confirm_id, me)
    peer = state["b" if side == "a" else "a"]
    event_id = state["event_id"]
    if await safety.is_blocked_pair(session, me, peer):
        raise errors.ExchangeNotFound
    result = await get_redis().eval(  # type: ignore[misc]
        _CONFIRM_LUA, 1, key("xchg", "cfm", confirm_id), f"ok_{side}"
    )
    if result == 0:
        raise errors.ExchangeNotFound
    if result == 1:
        return ConfirmOut(status="waiting")
    # Both confirmed. Idempotent: a retry or the second caller re-runs the same upserts.
    first_time = (
        await session.execute(
            select(Connection.id).where(
                Connection.user_id == me,
                Connection.peer_id == peer,
                Connection.event_id == event_id,
                Connection.met_confirmed_at.is_not(None),
            )
        )
    ).scalar_one_or_none() is None
    for owner, other in ((me, peer), (peer, me)):
        contact = await identity.shared_contact(session, other)
        await _upsert(
            session,
            user_id=owner,
            peer_id=other,
            event_id=event_id,
            met=True,
            shared={"email": contact.email, "phone": contact.phone, "links": contact.links},
        )
    if first_time:
        outbox.emit(
            session,
            "connections.confirmed",
            {"event_id": event_id, "user_ids": sorted([me, peer])},
        )
    await session.commit()
    row = (
        await session.execute(
            select(Connection).where(
                Connection.user_id == me,
                Connection.peer_id == peer,
                Connection.event_id == event_id,
            )
        )
    ).scalar_one()
    return ConfirmOut(status="confirmed", connection=(await to_out(session, [row]))[0])


async def ensure_pair(session: AsyncSession, event_id: str, a: str, b: str) -> None:
    """Both CRM rows for a pair that connected in-app (accepted wave). No contact details:
    those are exchanged only by the in-person tap."""
    for owner, other in ((a, b), (b, a)):
        await _upsert(
            session, user_id=owner, peer_id=other, event_id=event_id, met=False, shared=None
        )


# --- CRM -------------------------------------------------------------------------------


async def to_out(session: AsyncSession, rows: list[Connection]) -> list[ConnectionOut]:
    by_event: dict[str, list[str]] = {}
    for c in rows:
        by_event.setdefault(c.event_id, []).append(c.peer_id)
    cards = {
        eid: await profiles.get_event_cards(session, eid, peers) for eid, peers in by_event.items()
    }
    active = await identity.get_cards(session, [c.peer_id for c in rows])
    out = []
    for c in rows:
        ok = active[c.peer_id].active
        out.append(
            ConnectionOut(
                id=c.id,
                event_id=c.event_id,
                peer=cards[c.event_id][c.peer_id],
                met_confirmed_at=c.met_confirmed_at,
                shared=SharedContact(**json.loads(c.shared))
                if c.shared and ok
                else SharedContact(),
                notes=c.notes,
                followup_drafts=[str(d) for d in c.followup_drafts] if ok else [],
                created_at=c.created_at,
            )
        )
    return out


async def list_mine(
    session: AsyncSession, me: str, event_id: str | None, cursor: str | None, limit: int
) -> tuple[list[ConnectionOut], str | None]:
    q = select(Connection).where(
        Connection.user_id == me, safety.not_blocked(me, Connection.peer_id)
    )
    if event_id:
        q = q.where(Connection.event_id == event_id)
    after = decode_cursor(cursor)
    if after:
        q = q.where(Connection.id < str(after))
    rows = list(
        (await session.execute(q.order_by(Connection.id.desc()).limit(limit + 1))).scalars()
    )
    rows, nxt = paginate(rows, limit, lambda c: c.id)
    return await to_out(session, rows), nxt


async def set_notes(
    session: AsyncSession, me: str, connection_id: str, notes: str | None
) -> ConnectionOut:
    row = await session.get(Connection, connection_id)
    if row is None or row.user_id != me:
        raise NotFound
    row.notes = notes or None
    await session.commit()
    await session.refresh(row)
    return (await to_out(session, [row]))[0]
