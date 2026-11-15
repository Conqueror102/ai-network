"""Bachs adapter (https://docs.bachs.io), the first PaymentProvider (doc 11 §9.4).

Plain REST over httpx, so there is no SDK to trust or pin. Written against:
- POST /v1/checkout-sessions        (guides/checkout/checkout-sessions)
- GET  /v1/payments/{payment_id}    (api-reference/payments/get-payment)
- POST /v1/refunds                  (guides/refunds)
- webhook signing                   (guides/webhooks/overview)
Sandbox: https://sandbox-api.bachs.io with `sk_sandbox_` keys; live is a key swap.
"""

import hashlib
import hmac
import json
import time
from typing import Any

import httpx

from app.adapters.payments.port import (
    Checkout,
    PaymentError,
    PaymentStatus,
    WebhookEvent,
    WebhookInvalid,
    to_decimal_string,
    to_minor,
)

TOLERANCE_S = 300
_EVENT_TYPES = {
    "collection.succeeded": "payment.succeeded",
    "collection.failed": "payment.failed",
    "refund.paid": "payment.refunded",
}
_STATUS = {
    "succeeded": "succeeded",
    "accepted": "succeeded",
    "overpaid": "succeeded",
    "failed": "failed",
    "expired": "failed",
    "cancelled": "failed",
    "refunded": "refunded",
    "partially_refunded": "refunded",
    "auto_refunded": "refunded",
}  # created, processing, underpaid -> pending


class BachsPayments:
    name = "bachs"

    def __init__(
        self,
        api_key: str,
        webhook_secret: str,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._secrets = [s for s in webhook_secret.split(",") if s]  # rotation: old,new
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=10,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    async def _call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        try:
            r = await self._http.request(method, path, json=body)
        except httpx.HTTPError as e:
            raise PaymentError(f"bachs unreachable: {type(e).__name__}") from e
        if r.status_code >= 400:
            try:
                code = r.json().get("error_code", "")
            except ValueError:
                code = ""
            # never echo the response body: it can contain customer details
            raise PaymentError(f"bachs {r.status_code} {code}".strip())
        return r.json()

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
        data = await self._call(
            "POST",
            "/v1/checkout-sessions",
            {
                "pricing": {
                    "currency": currency.upper(),
                    "amount": to_decimal_string(amount_minor, currency),
                },
                "customer": {"email": customer_email},
                "success_url": success_url,
                "reference": reference,
                "metadata": {**metadata, "description": description[:200]},
            },
        )
        return Checkout(provider_ref=data["checkout_id"], url=data["checkout_url"])

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> WebhookEvent:
        h = {k.lower(): v for k, v in headers.items()}
        timestamp, signatures = "", []
        if "x-bachs-signature-v2" in h:  # t=<unix>,v1=<hex>[,v1=<hex> during rotation]
            for part in h["x-bachs-signature-v2"].split(","):
                k, _, v = part.strip().partition("=")
                if k == "t":
                    timestamp = v
                elif k == "v1":
                    signatures.append(v)
        else:
            timestamp = h.get("x-bachs-timestamp", "")
            signatures = [h["x-bachs-signature"]] if "x-bachs-signature" in h else []
        if not timestamp.isdigit() or not signatures:
            raise WebhookInvalid("missing signature")
        if abs(time.time() - int(timestamp)) > TOLERANCE_S:
            raise WebhookInvalid("stale timestamp")
        signed = timestamp.encode() + b"." + body
        expected = [hmac.new(s.encode(), signed, hashlib.sha256).hexdigest() for s in self._secrets]
        if not any(hmac.compare_digest(e, s) for e in expected for s in signatures):
            raise WebhookInvalid("bad signature")
        try:
            event: dict[str, Any] = json.loads(body)
            data: dict[str, Any] = event.get("data") or {}
            amount, currency = data.get("amount"), data.get("currency")
            return WebhookEvent(
                event_id=event["id"],
                type=_EVENT_TYPES.get(event["type"], "other"),
                provider_ref=data.get("charge_id"),
                raw={"type": event["type"], "checkout_id": data.get("checkout_id")},
                reference=data.get("reference"),
                amount_minor=to_minor(amount, currency) if amount and currency else None,
                currency=currency,
            )
        except (ValueError, KeyError, TypeError, PaymentError) as e:
            raise WebhookInvalid("malformed event") from e

    async def get_payment(self, provider_ref: str) -> PaymentStatus:
        data = await self._call("GET", f"/v1/payments/{provider_ref}")
        return PaymentStatus(
            provider_ref=data["payment_id"],
            status=_STATUS.get(data["status"], "pending"),
            amount_minor=to_minor(data["amount"], data["currency"]),
            currency=data["currency"],
        )

    async def refund(
        self, provider_ref: str, *, amount_minor: int | None = None, idempotency_key: str
    ) -> None:
        body: dict[str, Any] = {
            "charge_id": provider_ref,
            "reference": idempotency_key[:128],
            "idempotency_key": idempotency_key[:255],
        }
        if amount_minor is not None:
            # refunds are denominated in the payment's currency; look it up, do not guess
            payment = await self.get_payment(provider_ref)
            body["amount"] = to_decimal_string(amount_minor, payment.currency)
        await self._call("POST", "/v1/refunds", body)
