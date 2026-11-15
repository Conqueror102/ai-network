"""Twilio Programmable SMS (fallback). We send our own code so both providers share
one verification path; Twilio Verify would generate and check codes itself."""

from typing import Literal

import httpx

from app.adapters.otp.port import OtpSendError


class TwilioSmsOtp:
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, messaging_service_sid: str) -> None:
        self._sid, self._svc = account_sid, messaging_service_sid
        self._http = httpx.AsyncClient(
            base_url="https://api.twilio.com", timeout=5, auth=(account_sid, auth_token)
        )

    async def send(
        self, *, channel: Literal["phone", "email"], destination: str, code: str
    ) -> None:
        if channel != "phone":
            raise OtpSendError("twilio adapter only sends to phones")
        try:
            r = await self._http.post(
                f"/2010-04-01/Accounts/{self._sid}/Messages.json",
                data={
                    "To": destination,
                    "MessagingServiceSid": self._svc,
                    "Body": f"Your AiNetwork code is {code}. It expires in 10 minutes.",
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise OtpSendError(f"twilio: {type(e).__name__}") from e
