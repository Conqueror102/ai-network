"""Opaque keyset cursors (00 §4). Never OFFSET."""

import base64
import json
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.errors import ValidationFailed

T = TypeVar("T")
MAX_LIMIT = 100
DEFAULT_LIMIT = 25


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


def encode_cursor(value: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> Any:
    if not cursor:
        return None
    try:
        pad = "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(cursor + pad))
    except (ValueError, UnicodeDecodeError) as e:
        raise ValidationFailed("Invalid cursor", code="invalid_cursor") from e


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, limit))


def paginate(rows: list[T], limit: int, key: Any) -> tuple[list[T], str | None]:
    """`rows` must have been fetched with LIMIT limit+1. `key(row)` -> cursor value."""
    if len(rows) > limit:
        rows = rows[:limit]
        return rows, encode_cursor(key(rows[-1]))
    return rows, None
