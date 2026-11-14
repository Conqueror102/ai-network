import hashlib
import hmac
import json
from typing import Any

from app.adapters.payments.port import (
    Checkout,
    PaymentStatus,
    WebhookEvent,
    WebhookInvalid,
)

FAKE_SECRET = b"fake-webhook-secret"


class FakePayments:
    name = "fake"

    def __init__(self) -> None:
        self.payments: dict[str, PaymentStatus] = {}
        self.refunds: list[str] = []

    async def create_checkout(
        self,
        *,
        reference: str,
        amount_minor: int,
        currency: str,
        customer_email: str,
        description: str,
        success_url: str,
        metadata: dict[str, str],
    ) -> Checkout:
        ref = f"fakepay_{reference}"
        self.payments[ref] = PaymentStatus(ref, "pending", amount_minor, currency)
        return Checkout(ref, f"https://fake-pay.local/checkout/{ref}")

    @staticmethod
    def sign(body: bytes) -> str:
        return hmac.new(FAKE_SECRET, body, hashlib.sha256).hexdigest()

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        if not hmac.compare_digest(self.sign(body), headers.get("x-fake-signature", "")):
            raise WebhookInvalid("bad signature")
        data: dict[str, Any] = json.loads(body)
        return WebhookEvent(data["id"], data["type"], data.get("provider_ref"), data)

    async def get_payment(self, provider_ref: str) -> PaymentStatus:
        return self.payments[provider_ref]

    async def refund(
        self, provider_ref: str, *, amount_minor: int | None = None, idempotency_key: str
    ) -> None:
        self.refunds.append(provider_ref)
        self.payments[provider_ref].status = "refunded"
