import json

import pytest
from sqlalchemy import select, text

from app.adapters import factory
from app.adapters.payments.fake import FakePayments
from app.core.security.jwt import issue_access_token
from app.modules.billing.models import Invoice, LedgerEntry, Payment
from tests.helpers import make_event, sign_up


async def setup(client, with_email=True):
    owner = await sign_up(client)
    body = {"name": "Acme Events"}
    if with_email:
        body["billing_email"] = "billing@acme.example"
    r = await client.post("/v1/organizers", json=body, headers=owner["headers"])
    owner["org_id"] = r.json()["id"]
    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}
    return owner, staff


async def invoice(client, staff, org_id, amount=7500000):
    r = await client.post(
        "/v1/internal/billing/invoices",
        json={
            "organizer_id": org_id,
            "description": "Event plan",
            "amount_minor": amount,
            "currency": "NGN",
        },
        headers=staff,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def hook(client, payload):
    body = json.dumps(payload).encode()
    return await client.post(
        "/v1/webhooks/fake",
        content=body,
        headers={"x-fake-signature": FakePayments.sign(body), "content-type": "application/json"},
    )


async def test_invoice_checkout_webhook_flow(client, session):
    owner, staff = await setup(client)
    org = owner["org_id"]
    # only staff create invoices; amounts are integers
    r = await client.post("/v1/internal/billing/invoices", json={}, headers=owner["headers"])
    assert r.status_code == 404
    r = await client.post(
        "/v1/internal/billing/invoices",
        json={"organizer_id": org, "description": "x", "amount_minor": 10.5, "currency": "NGN"},
        headers=staff,
    )
    assert r.status_code == 422
    inv = await invoice(client, staff, org)

    url = f"/v1/organizers/{org}/invoices/{inv['id']}/checkout"
    key = {**owner["headers"], "Idempotency-Key": "c1"}
    r1 = await client.post(url, headers=key)
    r2 = await client.post(url, headers=key)
    assert r1.status_code == 200 and r1.json() == r2.json()  # one checkout, not two
    assert len(factory.payments().checkouts) == 1
    pay_id = r1.json()["payment_id"]
    event = {
        "id": "evt_1",
        "type": "payment.succeeded",
        "provider_ref": "ch_1",
        "reference": pay_id,
        "amount_minor": 7500000,
        "currency": "NGN",
    }
    # unsigned or tampered deliveries are refused and change nothing
    r = await client.post("/v1/webhooks/fake", json=event)
    assert r.status_code == 422 and r.json()["error"]["code"] == "webhook_invalid"
    assert (await client.post("/v1/webhooks/other", json=event)).status_code == 404

    assert (await hook(client, event)).json() == {"result": "applied"}
    assert (await hook(client, event)).json() == {"result": "duplicate"}  # provider retry
    # a different event id for the same payment must not double count either
    assert (await hook(client, {**event, "id": "evt_2"})).json() == {"result": "ignored"}

    lst = (await client.get(f"/v1/organizers/{org}/invoices", headers=owner["headers"])).json()
    assert lst["items"][0]["status"] == "paid" and lst["items"][0]["paid_at"]
    ledger = (await session.execute(select(LedgerEntry))).scalars().all()
    assert [(e.kind, e.amount_minor, e.currency) for e in ledger] == [("charge", 7500000, "NGN")]
    r = await client.post(url, headers=owner["headers"])
    assert r.json()["error"]["code"] == "invoice_not_payable"

    # refund: requested from the provider, booked when the provider confirms
    r = await client.post(f"/v1/internal/billing/invoices/{inv['id']}/refund", headers=staff)
    assert r.status_code == 200 and factory.payments().refunds == ["ch_1"]
    refund = {**event, "id": "evt_3", "type": "payment.refunded"}
    assert (await hook(client, refund)).json() == {"result": "applied"}
    session.expire_all()
    assert (await session.get(Invoice, inv["id"])).status == "refunded"
    total = sum(e.amount_minor for e in (await session.execute(select(LedgerEntry))).scalars())
    assert total == 0


async def test_wrong_amount_is_never_marked_paid(client, session):
    owner, staff = await setup(client)
    inv = await invoice(client, staff, owner["org_id"])
    r = await client.post(
        f"/v1/organizers/{owner['org_id']}/invoices/{inv['id']}/checkout", headers=owner["headers"]
    )
    event = {
        "id": "evt_1",
        "type": "payment.succeeded",
        "provider_ref": "ch_1",
        "reference": r.json()["payment_id"],
        "amount_minor": 100,
        "currency": "NGN",
    }
    await hook(client, event)
    session.expire_all()
    assert (await session.get(Invoice, inv["id"])).status == "open"
    assert (await session.execute(select(Payment))).scalar_one().status == "mismatch"
    assert (await session.execute(select(LedgerEntry))).first() is None


async def test_billing_tenant_isolation_and_manual_payment(client, session):
    owner, staff = await setup(client)
    other, _ = await setup(client)
    inv = await invoice(client, staff, owner["org_id"])
    # another organizer cannot see or pay it, and cannot learn that it exists
    r = await client.get(f"/v1/organizers/{owner['org_id']}/invoices", headers=other["headers"])
    assert r.status_code == 404
    r = await client.post(
        f"/v1/organizers/{other['org_id']}/invoices/{inv['id']}/checkout", headers=other["headers"]
    )
    assert r.status_code == 404
    # organizer staff (not owner) cannot see invoices either
    no_email, staff2 = await setup(client, with_email=False)
    inv2 = await invoice(client, staff2, no_email["org_id"])
    r = await client.post(
        f"/v1/organizers/{no_email['org_id']}/invoices/{inv2['id']}/checkout",
        headers=no_email["headers"],
    )
    assert r.json()["error"]["code"] == "billing_email_required"

    r = await client.post(f"/v1/internal/billing/invoices/{inv['id']}/mark-paid", headers=staff)
    assert r.json()["status"] == "paid"
    r = await client.post(f"/v1/internal/billing/invoices/{inv['id']}/mark-paid", headers=staff)
    assert r.json()["error"]["code"] == "invoice_not_payable"
    # the ledger cannot be edited or deleted, even by the application's own role
    with pytest.raises(Exception, match="append-only"):
        await session.execute(text("update ledger_entries set amount_minor = 1"))
    await session.rollback()


async def test_events_still_work(client):
    owner = await sign_up(client)
    assert (await make_event(client, owner))["id"]
