"""Coarse "active in the last 30 minutes" signal (05 §5 `both_present_now`).

One Redis key per user, refreshed by any authenticated request. Never exposed to
clients: it only feeds the matching context score.
"""

import contextlib

from redis.exceptions import RedisError

from app.core.redis import get_redis, key

ACTIVE_S = 1800


async def touch(user_id: str) -> None:
    with contextlib.suppress(RedisError):
        await get_redis().set(key("hb", "user", user_id), "1", ex=ACTIVE_S)


async def active_ids(user_ids: list[str]) -> set[str]:
    if not user_ids:
        return set()
    try:
        values = await get_redis().mget([key("hb", "user", u) for u in user_ids])
    except RedisError:
        return set()
    return {u for u, v in zip(user_ids, values, strict=True) if v}
