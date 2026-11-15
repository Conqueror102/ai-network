"""The Bachs adapter against the request and webhook shapes in docs.bachs.io."""

import hashlib
import hmac
import json
import time

import httpx
import pytest

from app.adapters.payments.bachs import BachsPayments
from app.adapters.payments.port import PaymentError, WebhookInvalid, to_decimal_string, to_minor

SECRET = "whsec_test"


def adapter(handler=None, secret=SECRET):
    transport = httpx.MockTransport(handler or (lambda r: httpx.Response(500)))
    return BachsPayments(
        "sk_sandbox_x", secret, "https://sandbox-api.bachs.io", transport=transport
    )


def signed(body: bytes, secret=SECRET, ts=None, v2=True):
    ts = str(int(ts if ts is not None else time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    if v2:
        return {"X-Bachs-Signature-V2": f"t={ts},v1={sig}"}
    return {"X-Bachs-Timestamp": ts, "X-Bachs-Signature": sig}


EVENT = json.dumps(
    {
        "id": "evt_1",
        "type": "collection.succeeded",
        "created_at": "2026-09-22T10:41:18.402Z",
        "organization_id": "acct_1",
        "data": {
            "charge_id": "ch_1",
            "checkout_id": "chk_1",
            "reference": "pay_abc",
            "status": "SUCCEEDED",
            "amount": "75000.00",
            "currency": "NGN",
            "customer": {"email": "jane@example.com"},
        },
    }
).encode()


def test_money_conversion_is_exact():
    assert to_decimal_string(7500000, "NGN") == "75000.00"
    assert to_decimal_string(5, "USD") == "0.05"
    assert to_decimal_string(1500, "UGX") == "1500"  # zero-decimal currency
    assert to_minor("75000.00", "NGN") == 7500000
    assert to_minor("0.10", "USD") == 10  # 0.1 * 100 is not 10 in floats
    assert to_minor("1500", "UGX") == 1500
    with pytest.raises(PaymentError):
        to_minor("1.005", "USD")


async def test_create_checkout_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"checkout_id": "chk_9", "checkout_url": "https://pay.bachs.io/c/chk_9"}
        )

    checkout = await adapter(handler).create_checkout(
        reference="pay_abc",
        amount_minor=7500000,
        currency="ngn",
        customer_email="ops@org.example",
        description="Event plan",
        success_url="https://app.example/billing",
        metadata={"invoice_id": "inv_1"},
    )
    assert (checkout.provider_ref, checkout.url) == ("chk_9", "https://pay.bachs.io/c/chk_9")
    assert seen["url"] == "https://sandbox-api.bachs.io/v1/checkout-sessions"
    assert seen["auth"] == "Bearer sk_sandbox_x"
    assert seen["body"]["pricing"] == {"currency": "NGN", "amount": "75000.00"}
    assert seen["body"]["reference"] == "pay_abc"
    assert seen["body"]["customer"] == {"email": "ops@org.example"}


async def test_errors_do_not_leak_response_bodies():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"detail": "customer jane@example.com", "error_code": "VALIDATION_ERROR"}
        )

    with pytest.raises(PaymentError) as e:
        await adapter(handler).get_payment("ch_1")
    assert "VALIDATION_ERROR" in str(e.value) and "jane" not in str(e.value)


def test_webhook_signature_accepts_v2_legacy_and_rotation():
    a = adapter()
    for v2 in (True, False):
        ev = a.verify_webhook(body=EVENT, headers=signed(EVENT, v2=v2))
        assert (ev.event_id, ev.type, ev.provider_ref) == ("evt_1", "payment.succeeded", "ch_1")
        assert (ev.reference, ev.amount_minor, ev.currency) == ("pay_abc", 7500000, "NGN")
        assert "jane" not in json.dumps(ev.raw)  # customer details are not kept
    # during rotation the provider signs with both secrets; we may hold both too
    rotating = adapter(secret="old_secret,whsec_test")
    assert rotating.verify_webhook(body=EVENT, headers=signed(EVENT)).event_id == "evt_1"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Bachs-Signature-V2": "t=abc,v1=00"},
        signed(EVENT, secret="wrong"),
        signed(EVENT, ts=time.time() - 3600),  # replay of an old delivery
        signed(EVENT + b" "),  # body changed after signing
    ],
)
def test_webhook_rejects_bad_signatures(headers):
    with pytest.raises(WebhookInvalid):
        adapter().verify_webhook(body=EVENT, headers=headers)


async def test_get_payment_and_refund():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.content))
        if request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "payment_id": "ch_1",
                    "status": "partially_refunded",
                    "amount": "75000.00",
                    "currency": "NGN",
                },
            )
        return httpx.Response(200, json={"refund_id": "ref_1", "status": "processing"})

    a = adapter(handler)
    status = await a.get_payment("ch_1")
    assert (status.status, status.amount_minor) == ("refunded", 7500000)
    await a.refund("ch_1", amount_minor=100000, idempotency_key="refund_pay_abc")
    body = json.loads(calls[-1][2])
    assert calls[-1][:2] == ("POST", "/v1/refunds")
    assert body == {
        "charge_id": "ch_1",
        "reference": "refund_pay_abc",
        "idempotency_key": "refund_pay_abc",
        "amount": "1000.00",
    }
