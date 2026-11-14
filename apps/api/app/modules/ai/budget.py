"""Cost tracking and caps (06 §1): per-event spend, per-user daily assist calls."""

from redis.exceptions import RedisError

from app.core import clock
from app.core.config import get_settings
from app.core.errors import RateLimited
from app.core.redis import get_redis, key

# USD per million tokens (input, output). Unknown models cost 0 and are flagged in logs.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


async def add_event_spend(event_id: str | None, usd: float) -> float:
    if not event_id or usd <= 0:
        return 0.0
    try:
        r = get_redis()
        k = key("budget", "event", event_id)
        total = float(await r.incrbyfloat(k, usd))
        await r.expire(k, 14 * 24 * 3600)
    except RedisError:
        return 0.0
    return total


async def event_spend(event_id: str) -> float:
    try:
        return float(await get_redis().get(key("budget", "event", event_id)) or 0)
    except RedisError:
        return 0.0


async def event_over_budget(event_id: str | None) -> bool:
    if not event_id:
        return False
    return await event_spend(event_id) >= get_settings().ai_event_budget_usd


async def consume_daily_assist(user_id: str, *, premium: bool = False) -> None:
    cap = get_settings().ai_user_daily_assist_cap * (4 if premium else 1)
    k = key("quota", "assist", user_id, clock.now().strftime("%Y%m%d"))
    try:
        r = get_redis()
        n = await r.incr(k)
        await r.expire(k, 36 * 3600)
    except RedisError:
        return
    if n > cap:
        raise RateLimited("Daily wingman limit reached", code="ai_daily_limit", retry_after_s=3600)
