from typing import Protocol


class EmailSendError(Exception):
    pass


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html: str) -> None: ...
