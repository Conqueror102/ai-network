"""structlog JSON logging with PII scrubbing (08 §5)."""

import logging
import re
import sys
from typing import Any

import structlog

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d\s-]{8,14}\d")
_SENSITIVE_KEYS = {
    "password",
    "code",
    "otp",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "body",
    "phone",
    "email",
    "destination",
}


def scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _PHONE.sub("[phone]", _EMAIL.sub("[email]", value))
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in _SENSITIVE_KEYS else scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    return value


def _scrub_processor(_: Any, __: str, event_dict: Any) -> Any:
    out: dict[str, Any] = {}
    for k, v in event_dict.items():
        if k in (
            "timestamp",
            "level",
            "request_id",
            "trace_id",
            "user_id",
            "org_id",
            "event_id",
            "job_id",
            "route",
            "role",
        ):
            out[k] = v
        elif k.lower() in _SENSITIVE_KEYS:
            out[k] = "[redacted]"
        else:
            out[k] = scrub(v)
    return out


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(stream=sys.stdout, level=level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _scrub_processor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level)),
        cache_logger_on_first_use=True,
    )
