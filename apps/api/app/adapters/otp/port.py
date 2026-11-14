from typing import Literal, Protocol


class OtpSendError(Exception):
    pass


class OtpSender(Protocol):
    name: str

    async def send(
        self, *, channel: Literal["phone", "email"], destination: str, code: str
    ) -> None: ...
