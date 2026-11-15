"""Web Push (VAPID) for the v0 PWA. Expo push replaces this from v1.5."""

import asyncio
import json
from typing import Any

from pywebpush import WebPushException, webpush

from app.adapters.push.port import PushGone, PushSendError, PushTarget


class WebPushSender:
    def __init__(self, vapid_private_key: str, subject: str) -> None:
        self._key, self._subject = vapid_private_key, subject

    def _send(self, target: PushTarget, payload: dict[str, Any]) -> None:
        webpush(
            subscription_info={
                "endpoint": target.endpoint,
                "keys": {"p256dh": target.p256dh, "auth": target.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=self._key,
            vapid_claims={"sub": self._subject},
            ttl=3600,
            timeout=5,
        )

    async def send(self, target: PushTarget, payload: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self._send, target, payload)
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):
                raise PushGone from e
            raise PushSendError(str(status)) from e
