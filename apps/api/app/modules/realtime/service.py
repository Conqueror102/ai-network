"""WebSocket tickets and the per-socket delivery loop (07 §1)."""

import asyncio
import contextlib
import json
from collections.abc import Awaitable, Callable

import structlog
from redis.asyncio.client import PubSub

from app.core import clock
from app.core.errors import RateLimited
from app.core.redis import get_redis, key
from app.core.security.hashing import random_token
from app.modules.realtime.public import ONLINE_TTL_S

log = structlog.get_logger()
TICKET_TTL_S = 30
MAX_SOCKETS_PER_USER = 5
HEARTBEAT_S = 25
CLOSE_EXPIRED = 4001
CLOSE_BAD_TICKET = 4401
CLOSE_TOO_MANY = 4429


async def issue_ticket(user_id: str, token_exp: int) -> str:
    """Single use, 30 s. Keeps the long-lived JWT out of URLs and proxy logs."""
    ticket = random_token(24)
    await get_redis().set(key("ws", "ticket", ticket), f"{user_id}|{token_exp}", ex=TICKET_TTL_S)
    return ticket


async def redeem_ticket(ticket: str) -> tuple[str, int] | None:
    raw = await get_redis().getdel(key("ws", "ticket", ticket)) if ticket else None
    if not raw:
        return None
    user_id, _, exp = raw.partition("|")
    return user_id, int(exp)


async def acquire_slot(user_id: str) -> None:
    r = get_redis()
    k = key("ws", "count", user_id)
    n = await r.incr(k)
    await r.expire(k, 3600)
    if n > MAX_SOCKETS_PER_USER:
        await r.decr(k)
        raise RateLimited("Too many open connections", code="ws_too_many")


async def release_slot(user_id: str) -> None:
    r = get_redis()
    k = key("ws", "count", user_id)
    if await r.decr(k) <= 0:
        await r.delete(k, key("ws", "online", user_id))


async def mark_online(user_id: str) -> None:
    await get_redis().set(key("ws", "online", user_id), "1", ex=ONLINE_TTL_S)


async def pump(
    pubsub: PubSub,
    send_text: Callable[[str], Awaitable[None]],
    receive_text: Callable[[], Awaitable[str]],
    *,
    user_id: str,
    expires_at: int,
    heartbeat_s: float = HEARTBEAT_S,
) -> int:
    """Run one socket until it closes. Returns the close code to use.

    Server to client: envelopes from the subscribed channels. Client to server: only
    `{"type":"ping"}` and `{"type":"ack"}`; everything else is ignored, because every
    mutation goes over REST."""

    async def forward() -> None:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await send_text(message["data"])

    async def inbound() -> None:
        while True:
            raw = await receive_text()
            with contextlib.suppress(ValueError, TypeError, AttributeError):
                if json.loads(raw).get("type") == "ping":
                    await mark_online(user_id)
                    await send_text('{"type":"pong"}')

    async def lifetime() -> None:
        # the socket dies when the access token it was opened with would have expired
        while clock.now().timestamp() < expires_at:
            await mark_online(user_id)
            await asyncio.sleep(min(heartbeat_s, max(0.01, expires_at - clock.now().timestamp())))

    tasks = [asyncio.create_task(c) for c in (forward(), inbound(), lifetime())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        expired = tasks[2] in done and tasks[2].exception() is None
        return CLOSE_EXPIRED if expired else 1000
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
