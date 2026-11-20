"""00 §4: nobody learns where another attendee is, was, or when they were last
active. v0 has no radar, so the rule is simple: no payload about another person
carries a location, zone, check-in time or presence field.

The one exception is two-way meet-up location sharing (chat/location.py): both people
opt in for one confirmed meeting and see only distance and direction, on its own
endpoint. The sweep runs again while that is live, to prove nothing spills over."""

from datetime import timedelta

from app.core import clock, jobs, outbox
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

    async def sweep() -> int:
        checked = 0
        for url in seen:
            r = await client.get(url, headers=a["headers"])
            assert r.status_code == 200, f"{url}: {r.text}"
            checked += 1
            leaked = {k for k in keys_of(r.json()) if any(f in k.lower() for f in FORBIDDEN)}
            assert not leaked, f"{url} exposes {leaked}"
        return checked

    assert await sweep() == len(seen)

    # live two-way meet-up sharing must not leak into any of the above
    at = (clock.now() + timedelta(minutes=45)).replace(second=0, microsecond=0)
    at = at.replace(minute=at.minute - at.minute % 15)
    meet = f"/v1/conversations/{cid}/meet"
    pid = (
        await client.post(
            meet, json={"meeting_point": "Coffee stand", "at": at.isoformat()}, headers=a["headers"]
        )
    ).json()["id"]
    await client.post(meet, json={"accept_message_id": pid}, headers=b["headers"])
    clock.advance(at - clock.now() - timedelta(minutes=5))
    for who in (a, b):
        await client.post(f"{meet}/{pid}/sharing", json={"on": True}, headers=who["headers"])
    for who, lat in ((a, 6.43), (b, 6.4302)):
        r = await client.post(
            f"{meet}/{pid}/position",
            json={"lat": lat, "lng": 3.42, "accuracy_m": 10},
            headers=who["headers"],
        )
        assert r.status_code == 200, r.text
    assert r.json()["distance_m"] is not None
    await settle()
    assert await sweep() == len(seen)
