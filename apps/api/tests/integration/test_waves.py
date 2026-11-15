from datetime import timedelta

from sqlalchemy import select

from app.core import clock, jobs, outbox
from app.core.outbox import OutboxEvent
from app.modules.matching.models import MatchFeedback
from app.modules.safety.models import ModerationFlag
from app.modules.waves import jobs as wave_jobs
from app.modules.waves import service as wave_service
from app.modules.waves.models import Wave
from tests.helpers import join, make_event, sign_up


async def settle():
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()


async def room(client, n=2):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    people = [
        await join(client, owner, eid, name=f"P{i}", headline=f"Builder {i}", offer="fintech apps")
        for i in range(n)
    ]
    await settle()
    return owner, eid, people


async def wave(client, eid, sender, to, **extra):
    return await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": to["id"], "source": "directory", **extra},
        headers=sender["headers"],
    )


async def respond(client, user, wave_id, action):
    return await client.post(
        f"/v1/waves/{wave_id}/respond", json={"action": action}, headers=user["headers"]
    )


async def topics(session):
    return [e.topic for e in (await session.execute(select(OutboxEvent))).scalars()]


async def test_wave_accept_creates_conversation_and_connection(client, session):
    _, eid, (a, b) = await room(client)
    r = await wave(client, eid, a, b, note="Loved your talk on payments")
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["status"] == "pending" and w["to"]["display_name"] == "P1"
    assert (await wave(client, eid, a, b)).json()["error"]["code"] == "wave_already_exists"
    assert (await wave(client, eid, a, a)).json()["error"]["code"] == "recipient_unavailable"

    inbox = (await client.get(f"/v1/events/{eid}/waves/inbox", headers=b["headers"])).json()
    card = inbox["items"][0]["card"]
    assert card["from"]["display_name"] == "P0" and card["note"] == "Loved your talk on payments"
    assert card["why"] == "You're both at DevCon Lagos."
    assert "phone" not in str(card) and "email" not in str(card)
    # only the recipient can answer
    assert (await respond(client, a, w["id"], "accept")).status_code == 404

    r = await respond(client, b, w["id"], "accept")
    cid = r.json()["conversation_id"]
    assert cid.startswith("cnv_")
    assert (await respond(client, b, w["id"], "accept")).json()["error"]["code"] == (
        "wave_not_pending"
    )
    sent = (await client.get(f"/v1/events/{eid}/waves/sent", headers=a["headers"])).json()
    assert sent["items"][0]["status"] == "accepted" and sent["items"][0]["conversation_id"] == cid
    assert (await client.get(f"/v1/events/{eid}/waves/inbox", headers=b["headers"])).json()[
        "items"
    ] == []
    # both now have a CRM row without contact details, and the signals are logged
    for u in (a, b):
        items = (await client.get("/v1/connections", headers=u["headers"])).json()["items"]
        assert len(items) == 1 and items[0]["met_confirmed_at"] is None
        assert items[0]["shared"] == {"email": None, "phone": None, "links": []}
    signals = {f.signal for f in (await session.execute(select(MatchFeedback))).scalars()}
    assert signals == {"wave_sent", "wave_accepted"}
    assert {"waves.received", "waves.accepted", "chat.conversation_created"} <= set(
        await topics(session)
    )


async def test_mutual_waves_auto_accept(client, session):
    _, eid, (a, b) = await room(client)
    await wave(client, eid, a, b)
    r = await wave(client, eid, b, a)
    assert r.json()["status"] == "accepted" and r.json()["conversation_id"]
    sent = (await client.get(f"/v1/events/{eid}/waves/sent", headers=a["headers"])).json()
    assert sent["items"][0]["conversation_id"] == r.json()["conversation_id"]
    assert "waves.mutual" in await topics(session)


async def test_note_screen_fails_closed_and_pauses_repeat_offenders(client, session):
    from app.core import flags

    _, eid, (a, b, c) = await room(client, 3)
    r = await wave(client, eid, a, b, note="call me on +234 801 234 5678")
    assert r.json()["error"]["code"] == "note_rejected"
    assert (await session.execute(select(Wave))).first() is None  # nothing was created
    # AI down: the note cannot be screened, so the wave is not sent with it
    await flags.set_flag("ai.task.safety_screen", False)
    flags.clear_cache()
    r = await wave(client, eid, a, b, note="Nice to meet you")
    assert r.status_code == 503 and r.json()["error"]["code"] == "note_unavailable"
    assert (await wave(client, eid, a, b)).status_code == 201  # without a note it goes through
    await flags.set_flag("ai.task.safety_screen", None)
    flags.clear_cache()
    for _ in range(2):
        r = await wave(client, eid, a, c, note="you idiot")
        assert r.json()["error"]["code"] == "note_rejected"
    r = await wave(client, eid, a, c)
    assert r.json()["error"]["code"] == "waves_paused"
    flag = (await session.execute(select(ModerationFlag))).scalar_one()
    assert flag.kind == "wave_pause" and flag.user_id == a["id"]


async def test_wave_rate_limit_and_decline_streak(client, session):
    _, eid, people = await room(client, 8)
    a, rest = people[0], people[1:]
    for p in rest[:5]:
        assert (await wave(client, eid, a, p)).status_code == 201
    r = await wave(client, eid, a, rest[5])
    assert r.status_code == 429 and r.json()["error"]["code"] == "wave_limit_reached"
    clock.advance(timedelta(minutes=61))
    assert (await wave(client, eid, a, rest[5])).status_code == 201


async def test_decline_streak_pauses_sender(client, session, monkeypatch):
    """01 §14.3: too many "not now" answers in one event pauses sending for review."""
    monkeypatch.setattr(wave_service, "DECLINE_STREAK", 2)
    _, eid, (a, b, c, d, e) = await room(client, 5)
    for p in (b, c, d):
        wid = (await wave(client, eid, a, p)).json()["id"]
        assert (await respond(client, p, wid, "not_now")).status_code == 204
    flag = (await session.execute(select(ModerationFlag))).scalar_one()
    assert flag.kind == "wave_pause" and flag.user_id == a["id"]
    assert (await wave(client, eid, a, e)).json()["error"]["code"] == "waves_paused"


async def test_inbox_cap_holds_waves_without_telling_the_sender(client, session, monkeypatch):
    monkeypatch.setattr(wave_service, "INBOX_CAP", 2)
    _, eid, (star, a, b, c) = await room(client, 4)
    r1, r2, r3 = [await wave(client, eid, s, star) for s in (a, b, c)]
    assert r3.status_code == 201 and r3.json()["status"] == "pending"
    assert set(r3.json()) == set(r1.json())  # a held wave looks like any other
    inbox = (await client.get(f"/v1/events/{eid}/waves/inbox", headers=star["headers"])).json()
    assert [i["id"] for i in inbox["items"]] == [r2.json()["id"], r1.json()["id"]]
    assert (await respond(client, star, r3.json()["id"], "accept")).status_code == 404
    assert (await respond(client, star, r1.json()["id"], "not_now")).status_code == 204
    inbox = (await client.get(f"/v1/events/{eid}/waves/inbox", headers=star["headers"])).json()
    assert [i["id"] for i in inbox["items"]] == [r3.json()["id"], r2.json()["id"]]
    assert (await topics(session)).count("waves.received") == 3


async def test_maybe_later_resurfaces_once_then_declines_silently(client, session):
    _, eid, (a, b) = await room(client)
    wid = (await wave(client, eid, a, b)).json()["id"]
    assert (await respond(client, b, wid, "maybe_later")).status_code == 204
    inbox_url = f"/v1/events/{eid}/waves/inbox"
    assert (await client.get(inbox_url, headers=b["headers"])).json()["items"] == []
    assert (await respond(client, b, wid, "accept")).json()["error"]["code"] == "wave_not_pending"

    # 09:00 event-local (Africa/Lagos, UTC+1) on the next day
    now = clock.now()
    target = (now + timedelta(days=1)).replace(hour=8, minute=5, second=0, microsecond=0)
    clock.advance(target - now)
    await wave_jobs.resurface()
    await wave_jobs.resurface()
    assert (await topics(session)).count("waves.resurfaced") == 1
    items = (await client.get(inbox_url, headers=b["headers"])).json()["items"]
    assert items[0]["id"] == wid and items[0]["resurfaced"] is True
    # a second snooze is a quiet "not now"
    assert (await respond(client, b, wid, "maybe_later")).status_code == 204
    session.expire_all()
    assert (await session.get(Wave, wid)).status == "not_now"
    sent = (await client.get(f"/v1/events/{eid}/waves/sent", headers=a["headers"])).json()
    assert sent["items"][0]["status"] == "pending"


async def test_open_waves_expire_a_day_after_the_event(client, session):
    owner, eid, (a, b, c) = await room(client, 3)
    w1 = (await wave(client, eid, a, b)).json()["id"]
    w2 = (await wave(client, eid, a, c)).json()["id"]
    await respond(client, c, w2, "accept")
    await client.post(
        f"/v1/events/{eid}/status", json={"status": "ended"}, headers=owner["headers"]
    )
    await wave_jobs.expire()
    session.expire_all()
    assert (await session.get(Wave, w1)).status == "pending"  # not yet
    clock.advance(timedelta(hours=33))
    await wave_jobs.expire()
    session.expire_all()
    assert (await session.get(Wave, w1)).status == "expired"
    assert (await session.get(Wave, w2)).status == "accepted"
    sent = (await client.get(f"/v1/events/{eid}/waves/sent", headers=a["headers"])).json()
    assert {i["status"] for i in sent["items"]} == {"pending", "accepted"}
