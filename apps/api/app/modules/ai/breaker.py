"""Per-model circuit breaker in Redis: 5 consecutive failures => open for 60 s (06 §1)."""

from redis.exceptions import RedisError

from app.core.redis import get_redis, key

THRESHOLD = 5
OPEN_S = 60


async def is_open(model: str) -> bool:
    try:
        return bool(await get_redis().exists(key("breaker", model, "open")))
    except RedisError:
        return False


async def record_failure(model: str) -> None:
    try:
        r = get_redis()
        k = key("breaker", model, "fails")
        n = await r.incr(k)
        await r.expire(k, 300)
        if n >= THRESHOLD:
            await r.set(key("breaker", model, "open"), "1", ex=OPEN_S)
            await r.delete(k)
    except RedisError:
        return


async def record_success(model: str) -> None:
    try:
        await get_redis().delete(key("breaker", model, "fails"))
    except RedisError:
        return
