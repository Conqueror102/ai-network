from typing import Any

from app.adapters.push.port import PushGone, PushTarget


class FakePush:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.gone: set[str] = set()

    async def send(self, target: PushTarget, payload: dict[str, Any]) -> None:
        if target.endpoint in self.gone:
            raise PushGone
        self.sent.append((target.endpoint, payload))
