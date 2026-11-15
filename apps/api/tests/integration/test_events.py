from datetime import timedelta

from app.core import clock, jobs, outbox
from tests.helpers import check_in, make_event, sign_up


async def test_event_lifecycle_and_discovery(client):
    owner = await sign_up(client, name="Org Owner")
    event = await make_event(client, owner, publish=False)
    listed = (await client.get("/v1/events")).json()["items"]
    assert listed == []  # drafts are not discoverable
    attendee = await sign_up(client)
    assert (
        await client.get(f"/v1/events/{event['id']}", headers=attendee["headers"])
    ).status_code == 404
    await client.post(
        f"/v1/events/{event['id']}/status", json={"status": "published"}, headers=owner["headers"]
    )
    listed = (await client.get("/v1/events?city=NG-LA")).json()["items"]
    assert [e["id"] for e in listed] == [event["id"]] and listed[0]["address"] is None
    bad = await client.post(
        f"/v1/events/{event['id']}/status", json={"status": "published"}, headers=owner["headers"]
    )
    assert bad.json()["error"]["code"] == "invalid_status_transition"


async def test_address_only_for_approved(client):
    owner = await sign_up(client)
    event = await make_event(client, owner, gating="apply")
    a = await sign_up(client)
    url = f"/v1/events/{event['id']}"
    assert (await client.get(url, headers=a["headers"])).json()["address"] is None
    assert (await client.post(f"{url}/apply", headers=a["headers"])).json()["status"] == "pending"
    assert (await client.get(url, headers=a["headers"])).json()["address"] is None
    apps = (
        await client.get(f"{url}/applications?status=pending", headers=owner["headers"])
    ).json()["items"]
    r = await client.post(
        f"{url}/applications/{apps[0]['id']}/decide",
        json={"approve": True},
        headers=owner["headers"],
    )
    assert r.json()["status"] == "approved"
    assert (await client.get(url, headers=a["headers"])).json()["address"] is not None


async def test_checkin_rotating_qr(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    a = await sign_up(client)
    url = f"/v1/events/{event['id']}"
    token = (await client.get(f"{url}/door-qr", headers=owner["headers"])).json()["qr_token"]
    r = await client.post(f"{url}/checkin", json={"qr_token": "r.1.deadbeef"}, headers=a["headers"])
    assert r.json()["error"]["code"] == "qr_invalid"
    r = await client.post(f"{url}/checkin", json={"qr_token": token}, headers=a["headers"])
    assert r.status_code == 200 and r.json()["event_room_unlocked"]
    # idempotent on the same day
    r = await client.post(f"{url}/checkin", json={"qr_token": token}, headers=a["headers"])
    assert r.status_code == 200
    stats = (await client.get(f"{url}/stats/live", headers=owner["headers"])).json()
    assert stats["checked_in"] == 1 and sum(stats["checkins_last_hour"]) == 1
    # a screenshot of the QR is useless a few minutes later
    b = await sign_up(client)
    clock.advance(timedelta(minutes=3))
    r = await client.post(f"{url}/checkin", json={"qr_token": token}, headers=b["headers"])
    assert r.json()["error"]["code"] == "qr_stale"
    assert (await client.get(url, headers=a["headers"])).json()["status"] == "live"


async def test_checkin_requires_approval_and_window(client):
    owner = await sign_up(client)
    event = await make_event(client, owner, gating="apply")
    a = await sign_up(client)
    url = f"/v1/events/{event['id']}"
    token = (await client.get(f"{url}/door-qr", headers=owner["headers"])).json()["qr_token"]
    r = await client.post(f"{url}/checkin", json={"qr_token": token}, headers=a["headers"])
    assert r.json()["error"]["code"] == "checkin_not_approved"
    clock.advance(timedelta(hours=9))
    token = (await client.get(f"{url}/door-qr", headers=owner["headers"])).json()["qr_token"]
    r = await client.post(f"{url}/checkin", json={"qr_token": token}, headers=a["headers"])
    assert r.json()["error"]["code"] == "event_not_live"


async def test_capacity_and_static_qr(client):
    owner = await sign_up(client)
    event = await make_event(client, owner, capacity=1)
    url = f"/v1/events/{event['id']}"
    a, b = await sign_up(client), await sign_up(client)
    qr = (await client.get(f"{url}/door-qr", headers=owner["headers"])).json()
    assert qr["static_qr_token"] is None
    await client.patch(url, json={"static_door_qr_enabled": True}, headers=owner["headers"])
    static = (await client.get(f"{url}/door-qr", headers=owner["headers"])).json()[
        "static_qr_token"
    ]
    assert (
        await client.post(f"{url}/checkin", json={"qr_token": static}, headers=a["headers"])
    ).status_code == 200
    r = await client.post(f"{url}/checkin", json={"qr_token": static}, headers=b["headers"])
    assert r.json()["error"]["code"] == "event_full"


async def test_announcements(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    a = await sign_up(client)
    url = f"/v1/events/{event['id']}/announcements"
    assert (await client.get(url, headers=a["headers"])).json()["error"][
        "code"
    ] == "checkin_required"
    await check_in(client, owner, event["id"], a)
    r = await client.post(
        url, json={"body": "Keynote starts in 5 minutes"}, headers=owner["headers"]
    )
    assert r.status_code == 201
    r = await client.post(url, json={"body": "Again"}, headers=owner["headers"])
    assert r.status_code == 429 and r.json()["error"]["code"] == "announcement_rate_limited"
    assert (await client.post(url, json={"body": "hi"}, headers=a["headers"])).status_code == 404
    items = (await client.get(url, headers=a["headers"])).json()["items"]
    assert [i["body"] for i in items] == ["Keynote starts in 5 minutes"]


async def test_status_cron(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    from app.modules.events.jobs import sync_status

    await sync_status()
    r = await client.get(f"/v1/events/{event['id']}", headers=owner["headers"])
    assert r.json()["status"] == "live"
    clock.advance(timedelta(hours=9))
    await sync_status()
    r = await client.get(f"/v1/events/{event['id']}", headers=owner["headers"])
    assert r.json()["status"] == "ended"
    await outbox.drain()
    await jobs.run_pending()


async def test_organizer_members(client):
    owner, staff, outsider = await sign_up(client), await sign_up(client), await sign_up(client)
    event = await make_event(client, owner)
    org = owner["org_id"]
    assert (
        await client.get(f"/v1/events/{event['id']}/stats/live", headers=staff["headers"])
    ).status_code == 404
    r = await client.post(
        f"/v1/organizers/{org}/members",
        json={"user_id": staff["id"], "role": "staff"},
        headers=owner["headers"],
    )
    assert r.status_code == 201
    assert (
        await client.get(f"/v1/events/{event['id']}/stats/live", headers=staff["headers"])
    ).status_code == 200
    # staff cannot manage members; outsiders see nothing
    assert (
        await client.get(f"/v1/organizers/{org}/members", headers=staff["headers"])
    ).status_code == 404
    assert (
        await client.post(
            f"/v1/organizers/{org}/members",
            json={"user_id": outsider["id"]},
            headers=outsider["headers"],
        )
    ).status_code == 404
    r = await client.delete(f"/v1/organizers/{org}/members/{owner['id']}", headers=owner["headers"])
    assert r.json()["error"]["code"] == "last_owner"
