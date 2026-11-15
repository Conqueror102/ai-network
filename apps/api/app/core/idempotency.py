"""Idempotency-Key support for money/message-creating POSTs (00 §4)."""

import hashlib
import json
from typing import Any

from redis.exceptions import RedisError

from app.core.errors import Conflict
from app.core.redis import get_redis, key

TTL_S = 24 * 3600


def _hash(body: Any) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


async def lookup(user_id: str, idem_key: str | None, body: Any) -> dict[str, Any] | None:
    """Return the stored response for a replay, or None for a first-time request."""
    if not idem_key:
        return None
    try:
        raw = await get_redis().get(key("idem", user_id, idem_key[:128]))
    except RedisError:
        return None
    if raw is None:
        return None
    stored = json.loads(raw)
    if stored["hash"] != _hash(body):
        raise Conflict(
            "Idempotency-Key reused with a different request", code="idempotency_key_reused"
        )
    return stored["response"]  # type: ignore[no-any-return]


async def store(user_id: str, idem_key: str | None, body: Any, response: dict[str, Any]) -> None:
    if not idem_key:
        return
    try:
        await get_redis().set(
            key("idem", user_id, idem_key[:128]),
            json.dumps({"hash": _hash(body), "response": response}, default=str),
            ex=TTL_S,
        )
    except RedisError:
        return
