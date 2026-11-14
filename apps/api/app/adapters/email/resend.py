import httpx

from app.adapters.email.port import EmailSendError


class ResendEmail:
    def __init__(self, api_key: str, sender: str) -> None:
        self._from = sender
        self._http = httpx.AsyncClient(
            base_url="https://api.resend.com",
            timeout=5,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def send(self, *, to: str, subject: str, html: str) -> None:
        try:
            r = await self._http.post(
                "/emails", json={"from": self._from, "to": [to], "subject": subject, "html": html}
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise EmailSendError(type(e).__name__) from e
