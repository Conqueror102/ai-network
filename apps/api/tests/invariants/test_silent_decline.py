"""00 §4 / 08 §4: a sender can never tell that they were declined."""

from app.core import jobs, outbox
from tests.helpers import join, make_event, sign_up


async def _snapshot(client, eid, sender):
    sent = await client.get(f"/v1/events/{eid}/waves/sent", headers=sender["headers"])
    feed = await client.get(f"/v1/events/{eid}/matches", headers=sender["headers"])
    conns = await client.get("/v1/connections", headers=sender["headers"])
    return sent.content, [c["user_id"] for c in feed.json()["items"]], conns.content


async def test_silent_decline(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada", offer="fintech apps")
    others = [await join(client, owner, eid, name=n, offer="fintech apps") for n in "BCDE"]
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()
    ids = []
    for p in others:
        r = await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": p["id"], "source": "directory"},
            headers=a["headers"],
        )
        assert r.status_code == 201
        ids.append(r.json()["id"])
    before = await _snapshot(client, eid, a)
    before_events = await outbox.drain()

    # one declines, one snoozes, one blocks the sender, one does nothing
    b, c, d, _ = others
    await client.post(
        f"/v1/waves/{ids[0]}/respond", json={"action": "not_now"}, headers=b["headers"]
    )
    await client.post(
        f"/v1/waves/{ids[1]}/respond", json={"action": "maybe_later"}, headers=c["headers"]
    )
    await client.post("/v1/blocks", json={"user_id": a["id"]}, headers=d["headers"])

    assert await _snapshot(client, eid, a) == before  # byte for byte
    # and nothing was queued for delivery to the sender
    from sqlalchemy import select

    from app.core.outbox import OutboxEvent

    new = [
        e
        for e in (await session.execute(select(OutboxEvent))).scalars()
        if e.topic.startswith("waves.") and e.topic != "waves.received"
    ]
    assert new == [] and before_events >= 0
    # a second wave to the person who declined is still "already exists", same as anyone
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "directory"},
        headers=a["headers"],
    )
    assert r.json()["error"]["code"] == "wave_already_exists"
