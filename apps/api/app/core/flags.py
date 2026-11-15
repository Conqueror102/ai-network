"""Feature flags and kill switches: env defaults, Redis runtime overrides (doc 11 §6)."""

import time

from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.redis import get_redis, key

_cache: dict[str, tuple[float, str | None]] = {}
CACHE_S = 10.0


async def _override(name: str) -> str | None:
    hit = _cache.get(name)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        value: str | None = await get_redis().get(key("flags", name))
    except RedisError:
        value = hit[1] if hit else None
    _cache[name] = (time.monotonic(), value)
    return value


async def is_enabled(name: str, default: bool = True) -> bool:
    value = await _override(name)
    if value is not None:
        return value == "1"
    return get_settings().flags.get(name, default)


async def get_value(name: str, default: str) -> str:
    value = await _override(name)
    return value if value is not None else default


async def set_flag(name: str, value: bool | str | None) -> None:
    r = get_redis()
    if value is None:
        await r.delete(key("flags", name))
    else:
        v = ("1" if value else "0") if isinstance(value, bool) else value
        await r.set(key("flags", name), v)  # flags are the one namespace without TTL
    _cache.pop(name, None)


def clear_cache() -> None:
    _cache.clear()
