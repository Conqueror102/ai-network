"""Redis sliding-window rate limiter (03 §12)."""

import structlog
from fastapi import Request
from redis.exceptions import RedisError

from app.core import clock
from app.core.errors import RateLimited
from app.core.ids import new_id
from app.core.redis import get_redis, key

log = structlog.get_logger()

_LUA = """
local k = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', k, 0, now - window)
local n = redis.call('ZCARD', k)
if n >= limit then
  local oldest = redis.call('ZRANGE', k, 0, 0, 'WITHSCORES')
  return {0, math.ceil((tonumber(oldest[2]) + window - now) / 1000)}
end
redis.call('ZADD', k, now, ARGV[4])
redis.call('PEXPIRE', k, window)
return {1, 0}
"""


async def hit(
    scope: str,
    ident: str,
    *,
    limit: int,
    window_s: int,
    code: str = "rate_limited",
    fail_open: bool = True,
) -> None:
    """Record one hit; raise RateLimited when over `limit` per rolling `window_s`."""
    try:
        allowed, retry = await get_redis().eval(  # type: ignore[misc]
            _LUA,
            1,
            key("rl", scope, ident),
            str(int(clock.now().timestamp() * 1000)),
            str(window_s * 1000),
            str(limit),
            new_id("h"),
        )
    except RedisError:
        log.warning("ratelimit_redis_unavailable", scope=scope, fail_open=fail_open)
        if fail_open:
            return
        raise RateLimited(
            "Temporarily unavailable, try again shortly", code=code, retry_after_s=30
        ) from None
    if not allowed:
        raise RateLimited(code=code, retry_after_s=max(1, int(retry)))


async def peek(scope: str, ident: str, *, window_s: int) -> int:
    r = get_redis()
    k = key("rl", scope, ident)
    await r.zremrangebyscore(k, 0, int(clock.now().timestamp() * 1000) - window_s * 1000)
    return int(await r.zcard(k))


def client_ip(request: Request) -> str:
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf
    return request.client.host if request.client else "unknown"


def limiter(scope: str, limit: int, window_s: int):  # type: ignore[no-untyped-def]
    """Per-IP limiter dependency for unauthenticated routes."""

    async def dep(request: Request) -> None:
        await hit(scope, client_ip(request), limit=limit, window_s=window_s)

    return dep
