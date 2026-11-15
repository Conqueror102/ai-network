from datetime import UTC, datetime, timedelta

from app.adapters import factory
from app.core import clock, jobs, outbox
from app.modules.notifications.service import quiet_delay_s
from tests.helpers import join, make_event, sign_up


def goto(hour: int, minute: int = 0) -> None:
    """Move the app clock forward to the next HH:MM UTC (tokens are already issued)."""
    now = clock.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    clock.advance(target - now)


async def settle():
    for _ in range(4):
        await outbox.drain()
        await jobs.run_pending()


async def subscribe(client, user, endpoint):
    r = await client.post(
        "/v1/me/push-subscriptions",
        json={"endpoint": endpoint, "p256dh": "p" * 20, "auth": "a" * 10},
        headers=user["headers"],
    )
    assert r.status_code == 204, r.text


def test_quiet_hours():
    lagos = "Africa/Lagos"  # UTC+1
    assert quiet_delay_s(datetime(2026, 11, 15, 12, 0, tzinfo=UTC), lagos) == 0
    assert quiet_delay_s(datetime(2026, 11, 15, 21, 30, tzinfo=UTC), lagos) == 9.5 * 3600
    assert quiet_delay_s(datetime(2026, 11, 15, 5, 0, tzinfo=UTC), lagos) == 2 * 3600


async def test_wave_and_message_notifications(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    await subscribe(client, a, "https://push.example/a")
    await subscribe(client, b, "https://push.example/b")
    await subscribe(client, b, "https://push.example/b-old")
    push = factory.push()
    push.gone.add("https://push.example/b-old")
    await settle()
    goto(11)  # midday in Lagos: not quiet hours

    wid = (
        await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": b["id"], "source": "directory"},
            headers=a["headers"],
        )
    ).json()["id"]
    await settle()
    sent = [p for e, p in push.sent if e == "https://push.example/b"]
    assert sent[-1]["body"] == "Someone at DevCon Lagos wants to meet you"
    assert "Ada" not in str(sent[-1])  # no name on a wave push
    # the dead subscription was cleaned up
    r = await client.post("/v1/notifications/read", json={"all": False}, headers=b["headers"])
    assert r.status_code == 204
    inbox = (await client.get("/v1/notifications", headers=b["headers"])).json()["items"]
    assert [n["category"] for n in inbox] == ["wave"] and inbox[0]["read_at"] is None
    assert (await client.get("/v1/notifications/unread-count", headers=b["headers"])).json() == {
        "unread": 1
    }
    # nobody else can read or clear my inbox
    assert (await client.get("/v1/notifications", headers=a["headers"])).json()["items"] == []
    await client.post(
        "/v1/notifications/read", json={"ids": [inbox[0]["id"]]}, headers=a["headers"]
    )
    assert (await client.get("/v1/notifications/unread-count", headers=b["headers"])).json() == {
        "unread": 1
    }

    cid = (
        await client.post(
            f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=b["headers"]
        )
    ).json()["conversation_id"]
    await settle()
    to_a = [p for e, p in push.sent if e == "https://push.example/a"]
    assert to_a[-1]["body"] == "Bayo accepted your intro 🎉"

    # chat: push with a preview, but the text is never copied into the inbox table
    await client.post(
        f"/v1/conversations/{cid}/messages",
        json={"body": "Shall we meet by the coffee stand?"},
        headers=b["headers"],
    )
    await settle()
    to_a = [p for e, p in push.sent if e == "https://push.example/a"]
    assert to_a[-1]["title"] == "Bayo" and to_a[-1]["body"] == "Shall we meet by the coffee stand?"
    assert to_a[-1]["tag"] == f"conv:{cid}"
    inbox_a = (await client.get("/v1/notifications", headers=a["headers"])).json()["items"]
    assert "coffee" not in str(inbox_a)

    # muting a category stops the push; the rest keep working
    r = await client.put(
        "/v1/me/notification-prefs", json={"push": {"message": False}}, headers=a["headers"]
    )
    assert r.json()["push"]["message"] is False and r.json()["push"]["wave"] is True
    before = len(push.sent)
    await client.post(
        f"/v1/conversations/{cid}/messages", json={"body": "ping"}, headers=b["headers"]
    )
    await settle()
    assert len(push.sent) == before
    r = await client.put(
        "/v1/me/notification-prefs", json={"push": {"nope": False}}, headers=a["headers"]
    )
    assert r.status_code == 422


async def test_quiet_hours_hold_push_but_not_inbox(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    await subscribe(client, b, "https://push.example/b")
    await settle()
    goto(22, 30)  # 23:30 in Lagos
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "directory"},
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
    await outbox.drain()
    inbox = (await client.get("/v1/notifications", headers=b["headers"])).json()["items"]
    assert len(inbox) == 1  # in the app immediately
    assert [j[0] for j in jobs.pending()] == ["notifications.push"]  # held for the morning


async def test_announcement_fans_out_to_checked_in_people(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    people = [await join(client, owner, eid, name=n) for n in ("Ada", "Bayo")]
    outsider = await sign_up(client)
    for i, p in enumerate(people):
        await subscribe(client, p, f"https://push.example/{i}")
    await settle()
    goto(11)
    factory.push().sent.clear()
    r = await client.post(
        f"/v1/events/{eid}/announcements",
        json={"body": "Keynote starts in 5 minutes"},
        headers=owner["headers"],
    )
    assert r.status_code in (200, 201), r.text
    await settle()
    for p in people:
        inbox = (await client.get("/v1/notifications", headers=p["headers"])).json()["items"]
        assert inbox[0]["body"] == "Keynote starts in 5 minutes"
    assert (await client.get("/v1/notifications", headers=outsider["headers"])).json()[
        "items"
    ] == []
    assert len(factory.push().sent) == 2
