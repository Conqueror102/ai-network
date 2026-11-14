"""Termii SMS OTP (primary for NG routes)."""

from typing import Literal

import httpx

from app.adapters.otp.port import OtpSendError


class TermiiOtp:
    name = "termii"

    def __init__(self, api_key: str, sender_id: str) -> None:
        self._key, self._sender = api_key, sender_id
        self._http = httpx.AsyncClient(base_url="https://api.ng.termii.com", timeout=5)

    async def send(
        self, *, channel: Literal["phone", "email"], destination: str, code: str
    ) -> None:
        if channel != "phone":
            raise OtpSendError("termii only sends to phones")
        try:
            r = await self._http.post(
                "/api/sms/send",
                json={
                    "api_key": self._key,
                    "to": destination.lstrip("+"),
                    "from": self._sender,
                    "sms": f"Your AiNetwork code is {code}. It expires in 10 minutes.",
                    "type": "plain",
                    "channel": "dnd",
                },
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise OtpSendError(f"termii: {type(e).__name__}") from e
