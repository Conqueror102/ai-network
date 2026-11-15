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
    provider_ref: str | None  # the provider's id for the charge
    raw: dict[str, Any] = field(default_factory=dict)
    reference: str | None = None  # our reference, as passed to create_checkout
    amount_minor: int | None = None
    currency: str | None = None


ZERO_DECIMAL = {
    "BIF",
    "CLP",
    "DJF",
    "GNF",
    "JPY",
    "KMF",
    "KRW",
    "PYG",
    "RWF",
    "UGX",
    "VND",
    "VUV",
    "XAF",
    "XOF",
    "XPF",
}


def to_decimal_string(amount_minor: int, currency: str) -> str:
    """Minor units -> the decimal string providers expect. Integer maths only."""
    if currency.upper() in ZERO_DECIMAL:
        return str(amount_minor)
    sign = "-" if amount_minor < 0 else ""
    whole, cents = divmod(abs(amount_minor), 100)
    return f"{sign}{whole}.{cents:02d}"


def to_minor(amount: str, currency: str) -> int:
    """Provider decimal string -> minor units, without ever touching a float."""
    from decimal import Decimal

    scale = 1 if currency.upper() in ZERO_DECIMAL else 100
    value = Decimal(amount) * scale
    if value != value.to_integral_value():
        raise PaymentError(f"amount {amount!r} has more precision than {currency} allows")
    return int(value)


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
