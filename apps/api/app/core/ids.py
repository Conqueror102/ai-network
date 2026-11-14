"""Prefixed ULIDs (00 §4). Generated in Python, never in the DB."""

from ulid import ULID


def new_id(prefix: str) -> str:
    return f"{prefix}_{ULID()}"
