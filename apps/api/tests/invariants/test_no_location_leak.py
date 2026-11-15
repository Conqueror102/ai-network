"""00 §4: nobody learns where another attendee is, was, or when they were last
active. v0 has no radar, so the rule is simple: no payload about another person
carries a location, zone, check-in time or presence field."""

from app.core import jobs, outbox
from tests.helpers import join, make_event, sign_up

FORBIDDEN = (
    "zone",
    "lat",
    "lng",
    "location",
    "checked_in_at",
    "scanned_at",
    "last_seen",
    "last_active",
    "online",
    "distance",
    "home_area",
)


async def settle():
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        out = set(value)
        for v in value.values():
            out |= keys_of(v)
        return out
    if isinstance(value, list):
        out = set()
        for v in value:
            out |= keys_of(v)
        return out
    return set()


async def test_people_payloads_carry_no_location_or_presence(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    goal = [{"intent": "meet", "target": {}, "raw_input": "meet fintech founders"}]
    kw = {"headline": "Fintech founder", "offer": "fintech payments", "goals": goal}
    a = await join(client, owner, eid, name="Ada", **kw)
    b = await join(client, owner, eid, name="Bayo", **kw)
    await settle()
    wid = (
        await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": b["id"], "source": "match_feed"},
            headers=a["headers"],
        )
    ).json()["id"]
    cid = (
        await client.post(
            f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=b["headers"]
        )
    ).json()["conversation_id"]
    await settle()

    seen = [
        f"/v1/events/{eid}/matches",
        f"/v1/events/{eid}/waves/sent",
        "/v1/conversations",
        f"/v1/conversations/{cid}/messages",
        "/v1/connections",
        "/v1/notifications",
        f"/v1/events/{eid}/waves/inbox",
    ]
    checked = 0
    for url in seen:
        r = await client.get(url, headers=a["headers"])
        assert r.status_code == 200, f"{url}: {r.text}"
        checked += 1
        leaked = {k for k in keys_of(r.json()) if any(f in k.lower() for f in FORBIDDEN)}
        assert not leaked, f"{url} exposes {leaked}"
    assert checked == len(seen)
