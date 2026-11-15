from typing import Literal

import structlog

from app.adapters.otp.port import OtpSendError
from app.core.config import get_settings

log = structlog.get_logger()


class FakeOtp:
    """Records codes instead of sending them. In dev the code is also logged."""

    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.sent: list[tuple[str, str, str]] = []
        self.fail = False

    async def send(
        self, *, channel: Literal["phone", "email"], destination: str, code: str
    ) -> None:
        if self.fail:
            raise OtpSendError("fake failure")
        self.sent.append((channel, destination, code))
        if get_settings().env == "dev":  # a code in the logs is a dev convenience only
            log.info("fake_otp_code", channel=channel, destination=destination, code=code)

    def last_code(self, destination: str) -> str:
        return next(c for _, d, c in reversed(self.sent) if d == destination)
