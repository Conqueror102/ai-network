"""00 §4 invariant 5: after a block neither person can see or reach the other, anywhere."""

from app.core import jobs, outbox
from tests.helpers import join, make_event, sign_up


async def test_blocks_are_absolute_and_silent(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada", headline="fintech", offer="fintech apps")
    b = await join(client, owner, eid, name="Bayo", headline="fintech", offer="fintech apps")
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()
    base = f"/v1/events/{eid}"
    wid = (
        await client.post(
            f"{base}/waves", json={"to_user": a["id"], "source": "directory"}, headers=b["headers"]
        )
    ).json()["id"]

    r = await client.post("/v1/blocks", json={"user_id": b["id"]}, headers=a["headers"])
    assert r.status_code == 204
    assert (
        await client.post("/v1/blocks", json={"user_id": b["id"]}, headers=a["headers"])
    ).status_code == 204  # idempotent
    assert (
        await client.post("/v1/blocks", json={"user_id": a["id"]}, headers=a["headers"])
    ).status_code == 422

    for me, other in ((a, b), (b, a)):
        directory = (await client.get(f"{base}/directory", headers=me["headers"])).json()
        assert other["id"] not in [p["user_id"] for p in directory["items"]]
        feed = (await client.get(f"{base}/matches", headers=me["headers"])).json()
        assert other["id"] not in [p["user_id"] for p in feed["items"]]
        r = await client.get(f"{base}/profiles/{other['id']}", headers=me["headers"])
        assert r.status_code == 404
        r = await client.post(
            f"{base}/waves",
            json={"to_user": other["id"], "source": "directory"},
            headers=me["headers"],
        )
        # the blocked person gets the same answer as for a hidden profile
        assert r.json()["error"]["code"] in ("recipient_unavailable", "wave_already_exists")
    # the pending wave vanished from the blocker's inbox and cannot be answered
    inbox = (await client.get(f"{base}/waves/inbox", headers=a["headers"])).json()
    assert inbox["items"] == []
    r = await client.post(
        f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=a["headers"]
    )
    assert r.status_code == 404
    # nothing is ever delivered to the blocked person about it
    from sqlalchemy import select

    from app.core.outbox import OutboxEvent

    for e in (await session.execute(select(OutboxEvent))).scalars():
        if e.topic == "safety.blocked":
            assert (e.payload["user_id"], e.payload["blocked_id"]) == (a["id"], b["id"])
