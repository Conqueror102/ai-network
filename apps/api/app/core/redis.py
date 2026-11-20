"""Redis client and namespaced key builder (doc 11 §7.5)."""

from redis.asyncio import Redis

from app.core.config import get_settings

NAMESPACES = {
    "rl",
    "idem",
    "ws",
    "radar",
    "cache",
    "flags",
    "breaker",
    "budget",
    "xchg",
    "otp",
    "hb",
    "metrics",
    "quota",
    "debounce",
    "meetloc",  # live meet-up location, two-way consent, minutes-long TTL
}

_client: Redis | None = None


def get_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            get_settings().redis_url,
            decode_responses=True,
            socket_timeout=2,
            socket_connect_timeout=2,
        )
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def key(namespace: str, *parts: str) -> str:
    if namespace not in NAMESPACES:
        raise ValueError(f"unknown redis namespace: {namespace}")
    return ":".join((get_settings().env, namespace, *parts))
