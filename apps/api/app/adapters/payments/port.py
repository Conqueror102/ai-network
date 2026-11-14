"""PaymentProvider port (doc 11 §9.4). Amounts are integer minor units."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class PaymentError(Exception):
    pass


class WebhookInvalid(PaymentError):
    pass


@dataclass
class Checkout:
    provider_ref: str
    url: str


@dataclass
class PaymentStatus:
    provider_ref: str
    status: str  # pending | succeeded | failed | refunded
    amount_minor: int
    currency: str


@dataclass
class WebhookEvent:
    event_id: str
    type: str  # payment.succeeded | payment.failed | payment.refunded | other
    provider_ref: str | None
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    name: str

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
    ) -> Checkout: ...

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEvent: ...

    async def get_payment(self, provider_ref: str) -> PaymentStatus: ...

    async def refund(
        self, provider_ref: str, *, amount_minor: int | None = None, idempotency_key: str
    ) -> None: ...
