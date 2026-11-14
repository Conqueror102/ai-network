"""Injectable clock so time-dependent logic can be time-warped in tests."""

from datetime import UTC, datetime, timedelta

_offset = timedelta(0)
_frozen: datetime | None = None


def now() -> datetime:
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC) + _offset


def freeze(at: datetime) -> None:
    global _frozen
    _frozen = at


def advance(delta: timedelta) -> None:
    global _offset, _frozen
    if _frozen is not None:
        _frozen = _frozen + delta
    else:
        _offset += delta


def reset() -> None:
    global _offset, _frozen
    _offset = timedelta(0)
    _frozen = None
