"""08 §6: an organizer runs the room, not the conversations. They get counts and the
people who applied to their event. They never see who waved at whom, who matched,
what was said, or anybody's address book."""

from app.core import jobs, outbox
from tests.helpers import join, make_event, sign_up

PRIVATE_WORDS = ("wave", "message", "conversation", "match", "note", "phone", "email")


async def settle():
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(keys_of(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(keys_of(v) for v in value))
    return set()


async def test_organizer_sees_aggregates_only(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    await settle()
    wid = (
        await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": b["id"], "source": "directory", "note": "Private hello"},
            headers=a["headers"],
        )
    ).json()["id"]
    cid = (
        await client.post(
            f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=b["headers"]
        )
    ).json()["conversation_id"]
    await settle()
    r = await client.post(
        f"/v1/conversations/{cid}/messages", json={"body": "Between us"}, headers=a["headers"]
    )
    assert r.status_code == 201, r.text

    # the organizer's own views carry no private field at all
    for url in (
        f"/v1/events/{eid}/stats/live",
        f"/v1/events/{eid}/applications",
        f"/v1/organizers/{owner['org_id']}/events",
    ):
        r = await client.get(url, headers=owner["headers"])
        assert r.status_code == 200, r.text
        leaked = {k for k in keys_of(r.json()) if any(w in k.lower() for w in PRIVATE_WORDS)}
        assert not leaked, f"{url} exposes {leaked}"
        assert "Private hello" not in r.text and "Between us" not in r.text

    # and attendee-to-attendee resources do not open for them
    for method, url, body in (
        ("GET", f"/v1/conversations/{cid}/messages", None),
        ("POST", f"/v1/conversations/{cid}/read", {"last_message_id": "msg_x"}),
        ("POST", f"/v1/conversations/{cid}/messages", {"body": "organizer butting in"}),
    ):
        r = await client.request(method, url, json=body, headers=owner["headers"])
        assert r.status_code == 404, f"{method} {url}: {r.status_code}"
    r = await client.post(
        f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=owner["headers"]
    )
    assert r.status_code == 404
    assert (await client.get("/v1/conversations", headers=owner["headers"])).json()["items"] == []
    assert (await client.get("/v1/connections", headers=owner["headers"])).json()["items"] == []
