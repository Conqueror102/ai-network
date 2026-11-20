"""Two-way location sharing for one confirmed meet-up.

The single, deliberate exception to "nobody learns where another attendee is"
(00 §4), so it is fenced in on every side:

- consent: each person turns it on for this one meeting; nothing flows until both have;
- audience: only the other person in the meet-up, as distance and a compass direction,
  never raw coordinates (indoor GPS is too rough for a pin anyway);
- time: positions are accepted from 30 minutes before the meeting to 15 minutes after,
  and sharing stops for good once both people tap "I'm here";
- storage: the latest position lives in Redis for a few minutes and is never written to
  the database, logs, the outbox or a push. Turning sharing off deletes it at once.
"""

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core import clock
from app.core.redis import get_redis, key

OPENS_BEFORE = timedelta(minutes=30)
CLOSES_AFTER = timedelta(minutes=15)
FRESH_FOR = timedelta(seconds=60)  # an older position is not shown
TTL_S = 300  # hard ceiling in Redis, whatever the app clock says
_COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


@dataclass(frozen=True)
class Fix:
    lat: float
    lng: float
    accuracy_m: float
    at: datetime


def window_open(meet_at: datetime, now: datetime) -> bool:
    return meet_at - OPENS_BEFORE <= now <= meet_at + CLOSES_AFTER


def _key(meet_id: str, user_id: str) -> str:
    return key("meetloc", meet_id, user_id)


async def save(meet_id: str, user_id: str, fix: Fix) -> None:
    value = {"lat": fix.lat, "lng": fix.lng, "acc": fix.accuracy_m, "ts": fix.at.isoformat()}
    await get_redis().set(_key(meet_id, user_id), json.dumps(value), ex=TTL_S)


async def load(meet_id: str, user_id: str) -> Fix | None:
    raw = await get_redis().get(_key(meet_id, user_id))
    if raw is None:
        return None
    v = json.loads(raw)
    fix = Fix(v["lat"], v["lng"], v["acc"], datetime.fromisoformat(v["ts"]))
    return fix if clock.now() - fix.at <= FRESH_FOR else None


async def forget(meet_id: str, *user_ids: str) -> None:
    if user_ids:
        await get_redis().delete(*(_key(meet_id, u) for u in user_ids))


def distance_m(a: Fix, b: Fix) -> float:
    """Haversine; plenty for a venue."""
    r = 6_371_000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def direction(a: Fix, b: Fix) -> str:
    """Compass direction from `a` towards `b`, to the nearest of eight."""
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lng - a.lng)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return _COMPASS[round(deg / 45) % 8]
