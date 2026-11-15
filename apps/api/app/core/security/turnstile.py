"""Cloudflare Turnstile verification (08 §6: gate before any OTP send)."""

import httpx

from app.core.config import get_settings


async def verify(token: str | None, ip: str | None) -> bool:
    s = get_settings()
    if not s.turnstile_enabled:
        return True
    if not token or s.turnstile_secret is None:
        return False
    try:
        async with httpx.AsyncClient(timeout=3) as http:
            r = await http.post(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={
                    "secret": s.turnstile_secret.get_secret_value(),
                    "response": token,
                    "remoteip": ip or "",
                },
            )
        return bool(r.json().get("success"))
    except httpx.HTTPError:
        return False  # fail closed: no challenge result, no SMS spend
