"""00 §4: the only way to reach someone is a wave they accept. There is no route
that opens a conversation or sends a message to a person who has not said yes."""

from app.core import jobs, outbox
from tests.helpers import join, make_event, sign_up


async def settle():
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()


async def setup(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    await settle()
    return eid, a, b


async def conversations(client, user):
    r = await client.get("/v1/conversations", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_no_conversation_before_acceptance(client, app):
    eid, a, b = await setup(client)
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "directory", "note": "Hello"},
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert "conversation_id" not in r.json() or r.json()["conversation_id"] is None
    assert await conversations(client, a) == [] and await conversations(client, b) == []

    # the sender cannot accept their own wave
    r = await client.post(
        f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=a["headers"]
    )
    assert r.status_code == 404

    # declined: still no channel, and nothing the sender can use to write
    await client.post(f"/v1/waves/{wid}/respond", json={"action": "not_now"}, headers=b["headers"])
    assert await conversations(client, a) == []


async def test_api_has_no_route_that_creates_a_conversation(app):
    """Conversations are born inside `waves.respond` only. A `POST /conversations`
    (or any DM-by-user-id route) would break the invariant, so its absence is pinned."""
    paths = app.openapi()["paths"]
    assert "post" not in paths.get("/v1/conversations", {})
    writers = [p for p, item in paths.items() if "post" in item and "/conversations" in p]
    assert all(p.startswith("/v1/conversations/{conversation_id}/") for p in writers), writers


async def test_wave_notes_are_short_and_cannot_carry_contact_details(client):
    eid, a, b = await setup(client)
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "directory", "note": "x" * 141},
        headers=a["headers"],
    )
    assert r.status_code == 422
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "directory", "body": "free text", "extra": 1},
        headers=a["headers"],
    )
    assert r.status_code == 422  # unknown fields are refused, not ignored
