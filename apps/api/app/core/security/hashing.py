"""Keyed hashing for OTPs and opaque tokens."""

import hashlib
import hmac
import secrets

from app.core.config import get_settings


def hmac_hash(value: str) -> str:
    pepper = get_settings().otp_pepper.get_secret_value().encode()
    return hmac.new(pepper, value.encode(), hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"
