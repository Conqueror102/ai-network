"""Realtime's public surface: publish an envelope to a user or an event audience.

Delivery is at-most-once; REST stays the source of truth (07 §1). Publishing never
raises: a Redis hiccup must not fail the request that triggered it.
"""

import json
from typing import Any, Literal

import structlog
from redis.exceptions import RedisError

from app.core import clock
from app.core.ids import new_id
from app.core.redis import get_redis, key

log = structlog.get_logger()
Audience = Literal["attendee", "stats"]
ONLINE_TTL_S = 60


def user_channel(user_id: str) -> str:
    return key("ws", "user", user_id)


def event_channel(event_id: str, audience: Audience) -> str:
    return key("ws", "event", event_id, audience)


def envelope(type_: str, payload: dict[str, Any]) -> str:
    return json.dumps(
        {"id": new_id("evt"), "type": type_, "ts": clock.now().isoformat(), "payload": payload},
        default=str,
    )


async def _publish(channel: str, type_: str, payload: dict[str, Any]) -> None:
    try:
        await get_redis().publish(channel, envelope(type_, payload))
    except RedisError:
        log.warning("ws_publish_failed", type=type_)


async def publish_user(user_id: str, type_: str, payload: dict[str, Any]) -> None:
    await _publish(user_channel(user_id), type_, payload)


async def publish_event(
    event_id: str, audience: Audience, type_: str, payload: dict[str, Any]
) -> None:
    await _publish(event_channel(event_id, audience), type_, payload)


async def is_online(user_id: str) -> bool:
    """True while the user has at least one live socket (refreshed by its heartbeat)."""
    try:
        return bool(await get_redis().exists(key("ws", "online", user_id)))
    except RedisError:
        return False


__all__ = ["event_channel", "is_online", "publish_event", "publish_user", "user_channel"]
