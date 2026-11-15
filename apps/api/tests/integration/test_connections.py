from datetime import timedelta

from sqlalchemy import select, text

from app.core import clock, jobs, outbox
from app.modules.connections.jobs import wrapup_sweep
from app.modules.connections.models import Connection
from app.modules.safety.models import Block
from tests.helpers import join, make_event, sign_up


async def _exchange(client, eid, a, b):
    tok = (
        await client.post("/v1/exchange/token", json={"event_id": eid}, headers=a["headers"])
    ).json()
    r = await client.post(
        "/v1/exchange/scan",
        json={"qr_payload": tok["qr_payload"], "event_id": eid},
        headers=b["headers"],
    )
    return tok, r


async def test_tap_to_exchange_dual_confirm(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada", headline="CTO at Paylane")
    b = await join(client, owner, eid, name="Bayo")
    # Ada shares her phone number, Bayo shares nothing
    r = await client.patch("/v1/me", json={"share_phone": True}, headers=a["headers"])
    assert r.status_code == 200, r.text

    tok, r = await _exchange(client, eid, a, b)
    assert tok["ttl_s"] == 60 and r.status_code == 200, r.text
    scan = r.json()
    assert scan["peer_card"]["display_name"] == "Ada" and "email" not in scan["peer_card"]
    cid = scan["confirm_id"]

    # the token is single use
    r = await client.post(
        "/v1/exchange/scan",
        json={"qr_payload": tok["qr_payload"], "event_id": eid},
        headers=b["headers"],
    )
    assert r.json()["error"]["code"] == "exchange_token_invalid"

    # the QR owner finds the confirm; a stranger cannot see or confirm it
    p = (await client.get("/v1/exchange/pending", headers=a["headers"])).json()
    assert p["confirm_id"] == cid and p["peer_card"]["display_name"] == "Bayo"
    c = await join(client, owner, eid, name="Chidi")
    assert (await client.get("/v1/exchange/pending", headers=c["headers"])).json() is None
    r = await client.post(f"/v1/exchange/{cid}/confirm", headers=c["headers"])
    assert r.status_code == 404

    # one-sided confirm writes nothing
    r = await client.post(f"/v1/exchange/{cid}/confirm", headers=b["headers"])
    assert r.json() == {"status": "waiting", "connection": None}
    assert (await session.execute(select(Connection))).first() is None

    r = await client.post(f"/v1/exchange/{cid}/confirm", headers=a["headers"])
    body = r.json()
    assert body["status"] == "confirmed"
    assert body["connection"]["peer"]["display_name"] == "Bayo"
    assert body["connection"]["shared"] == {"email": None, "phone": None, "links": []}
    # the other side, and a retry, get the same answer without duplicates
    r = await client.post(f"/v1/exchange/{cid}/confirm", headers=b["headers"])
    mine = r.json()["connection"]
    assert mine["shared"]["phone"] == a["phone"] and mine["shared"]["email"] is None
    assert mine["met_confirmed_at"]
    await client.post(f"/v1/exchange/{cid}/confirm", headers=b["headers"])
    assert len((await session.execute(select(Connection))).all()) == 2

    # contact details are encrypted at rest
    raw = (await session.execute(text("select shared from connections"))).scalars().all()
    assert all(a["phone"] not in (v or "") for v in raw)

    # CRM: private notes, owner only
    r = await client.patch(
        f"/v1/connections/{mine['id']}",
        json={"notes": "Follow up re: hiring"},
        headers=b["headers"],
    )
    assert r.json()["notes"] == "Follow up re: hiring"
    r = await client.patch(
        f"/v1/connections/{mine['id']}", json={"notes": "x"}, headers=a["headers"]
    )
    assert r.status_code == 404
    lst = (await client.get(f"/v1/connections?event_id={eid}", headers=a["headers"])).json()
    assert len(lst["items"]) == 1 and lst["items"][0]["notes"] is None  # notes never cross over

    await outbox.drain()


async def test_exchange_guards(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    other_eid = (await make_event(client, owner, name="Other"))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    outsider = await sign_up(client, name="Outsider")

    # not checked in: no token, no scan
    r = await client.post("/v1/exchange/token", json={"event_id": eid}, headers=outsider["headers"])
    assert r.json()["error"]["code"] == "checkin_required"
    tok, _ = await _exchange(client, eid, a, outsider)
    # self-scan
    tok, r = await _exchange(client, eid, a, a)
    assert r.json()["error"]["code"] == "exchange_self"
    # token is bound to its event
    tok = (
        await client.post("/v1/exchange/token", json={"event_id": eid}, headers=a["headers"])
    ).json()
    c = await join(client, owner, other_eid, name="Chidi")
    r = await client.post(
        "/v1/exchange/scan",
        json={"qr_payload": tok["qr_payload"], "event_id": other_eid},
        headers=c["headers"],
    )
    assert r.json()["error"]["code"] == "exchange_token_invalid"
    # a new token invalidates the previous one; expiry is enforced
    t1 = (
        await client.post("/v1/exchange/token", json={"event_id": eid}, headers=a["headers"])
    ).json()
    t2 = (
        await client.post("/v1/exchange/token", json={"event_id": eid}, headers=a["headers"])
    ).json()
    r = await client.post(
        "/v1/exchange/scan",
        json={"qr_payload": t1["qr_payload"], "event_id": eid},
        headers=b["headers"],
    )
    assert r.json()["error"]["code"] == "exchange_token_invalid"
    assert t1["qr_payload"] != t2["qr_payload"]

    # blocks are absolute: a blocked pair cannot exchange, and it looks like an expired code
    session.add(Block(user_id=a["id"], blocked_id=b["id"]))
    await session.commit()
    _, r = await _exchange(client, eid, a, b)
    assert r.json()["error"]["code"] == "exchange_token_invalid"
    _, r = await _exchange(client, eid, b, a)
    assert r.json()["error"]["code"] == "exchange_token_invalid"


async def test_block_hides_connection_and_delete_wipes_contact(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    c = await join(client, owner, eid, name="Chidi")
    await client.patch("/v1/me", json={"share_phone": True}, headers=a["headers"])
    for x in (a, c):
        _, r = await _exchange(client, eid, x, b)
        cid = r.json()["confirm_id"]
        await client.post(f"/v1/exchange/{cid}/confirm", headers=x["headers"])
        await client.post(f"/v1/exchange/{cid}/confirm", headers=b["headers"])
    items = (await client.get("/v1/connections", headers=b["headers"])).json()["items"]
    assert {i["peer"]["display_name"] for i in items} == {"Ada", "Chidi"}

    session.add(Block(user_id=c["id"], blocked_id=b["id"]))
    await session.commit()
    items = (await client.get("/v1/connections", headers=b["headers"])).json()["items"]
    assert [i["peer"]["display_name"] for i in items] == ["Ada"]
    assert items[0]["shared"]["phone"] == a["phone"]

    r = await client.delete("/v1/me", headers=a["headers"])
    assert r.status_code in (200, 202, 204), r.text
    await outbox.drain()
    items = (await client.get("/v1/connections", headers=b["headers"])).json()["items"]
    assert items[0]["shared"] == {"email": None, "phone": None, "links": []}
    assert items[0]["peer"]["display_name"] == "Deleted user"
    session.expire_all()
    row = (
        await session.execute(select(Connection).where(Connection.peer_id == a["id"]))
    ).scalar_one()
    assert row.shared is None


async def test_morning_after_followup_drafts(client, session):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    eid = event["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    _, r = await _exchange(client, eid, a, b)
    cid = r.json()["confirm_id"]
    await client.post(f"/v1/exchange/{cid}/confirm", headers=a["headers"])
    await client.post(f"/v1/exchange/{cid}/confirm", headers=b["headers"])
    await outbox.drain()

    r = await client.post(
        f"/v1/events/{eid}/status", json={"status": "ended"}, headers=owner["headers"]
    )
    assert r.status_code == 200, r.text
    await outbox.drain()
    jobs.clear_pending()

    await wrapup_sweep()  # too early: it is still the same day
    assert jobs.pending() == []
    clock.advance(timedelta(hours=40))
    await wrapup_sweep()
    await wrapup_sweep()
    assert [j[0] for j in jobs.pending()] == ["connections.wrapup"]  # deduped
    await jobs.run_pending()

    items = (await client.get("/v1/connections", headers=a["headers"])).json()["items"]
    assert items[0]["followup_drafts"] == [
        "Great meeting you at DevCon Lagos. Keen to continue our conversation this week?"
    ]
    # once per user, and a second run changes nothing
    from app.core.outbox import OutboxEvent

    topics = [
        e.topic
        for e in (await session.execute(select(OutboxEvent))).scalars()
        if e.topic == "connections.wrapup_ready"
    ]
    assert len(topics) == 2
    await wrapup_sweep()
    await jobs.run_pending()
    n = len(
        [
            e
            for e in (await session.execute(select(OutboxEvent))).scalars()
            if e.topic == "connections.wrapup_ready"
        ]
    )
    assert n == 2
