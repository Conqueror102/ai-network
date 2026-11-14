from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class PushTarget:
    id: str
    endpoint: str
    p256dh: str
    auth: str


class PushGone(Exception):
    """The subscription no longer exists; the caller deletes it."""


class PushSendError(Exception):
    pass


class PushSender(Protocol):
    async def send(self, target: PushTarget, payload: dict[str, Any]) -> None: ...
