"""Rotating door QR (01 §3.3, 08 §3): 60 s steps, accepted within +/- one step."""

import hashlib
import hmac

from app.core import clock

STEP_S = 60


def _mac(seed: str, message: str) -> str:
    return hmac.new(seed.encode(), message.encode(), hashlib.sha256).hexdigest()[:20]


def current_step() -> int:
    return int(clock.now().timestamp()) // STEP_S


def rotating_token(seed: str, event_id: str, step: int | None = None) -> str:
    step = current_step() if step is None else step
    return f"r.{step}.{_mac(seed, f'{event_id}:{step}')}"


def static_token(seed: str, event_id: str) -> str:
    return f"s.{_mac(seed, f'{event_id}:static')}"


def seconds_left() -> int:
    return STEP_S - int(clock.now().timestamp()) % STEP_S


def check(token: str, *, seed: str, event_id: str, static_enabled: bool) -> str:
    """Returns "ok", "stale" or "invalid"."""
    parts = token.split(".")
    if parts[0] == "s" and len(parts) == 2:
        ok = static_enabled and hmac.compare_digest(token, static_token(seed, event_id))
        return "ok" if ok else "invalid"
    if parts[0] != "r" or len(parts) != 3 or not parts[1].isdigit():
        return "invalid"
    step = int(parts[1])
    if not hmac.compare_digest(token, rotating_token(seed, event_id, step)):
        return "invalid"
    return "ok" if abs(current_step() - step) <= 1 else "stale"
