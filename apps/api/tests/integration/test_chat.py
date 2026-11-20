import json
from datetime import timedelta

from sqlalchemy import select, text

from app.core import clock, flags, jobs, outbox
from app.core.outbox import OutboxEvent
from app.core.security.jwt import issue_access_token
from app.modules.chat import jobs as chat_jobs
from app.modules.chat.models import Message
from app.modules.matching.models import MatchFeedback
from tests.helpers import join, make_event, sign_up


async def settle():
    for _ in range(3):
        await outbox.drain()
        await jobs.run_pending()


async def chat_pair(client, extra=0):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    people = [
        await join(
            client,
            owner,
            eid,
            name=n,
            headline="Fintech founder",
            offer="fintech payments",
            goals=[{"intent": "meet", "target": {}, "raw_input": "meet fintech founders"}],
        )
        for n in ["Ada", "Bayo", "Chidi"][: 2 + extra]
    ]
    await settle()
    a, b = people[0], people[1]
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
    return owner, eid, cid, people


async def send(client, cid, user, body, **kw):
    return await client.post(
        f"/v1/conversations/{cid}/messages",
        json={"body": body, **kw.pop("json", {})},
        headers={**user["headers"], **kw.pop("headers", {})},
    )


async def test_conversation_lifecycle(client, session):
    _, _eid, cid, (a, b, c) = await chat_pair(client, extra=1)
    # the wingman seeded icebreakers both can see
    msgs = (await client.get(f"/v1/conversations/{cid}/messages", headers=a["headers"])).json()
    assert [m["kind"] for m in msgs["items"]] == ["icebreakers"]
    assert msgs["items"][0]["sender_id"] is None and msgs["items"][0]["payload"]["options"]

    r = await send(client, cid, a, "Hi Bayo, great to connect", json={"ai_assisted": True})
    assert r.status_code == 201, r.text
    m1 = r.json()
    assert "ai_assisted" not in m1  # analytics only, never shown
    # outsiders get the same 404 as a missing conversation
    assert (await send(client, cid, c, "let me in")).status_code == 404
    assert (
        await client.get(f"/v1/conversations/{cid}/messages", headers=c["headers"])
    ).status_code == 404
    assert (await send(client, "cnv_nope", a, "x")).status_code == 404
    assert (await send(client, cid, a, "x" * 2001)).status_code == 422

    # idempotent send: the retry returns the first message, nothing is duplicated
    key = {"Idempotency-Key": "k1"}
    r1 = await send(client, cid, b, "Likewise!", headers=key)
    r2 = await send(client, cid, b, "Likewise!", headers=key)
    assert r1.json()["id"] == r2.json()["id"]
    r3 = await send(client, cid, b, "Different body", headers=key)
    assert r3.json()["error"]["code"] == "idempotency_key_reused"

    lst = (await client.get("/v1/conversations", headers=a["headers"])).json()["items"]
    assert len(lst) == 1 and lst[0]["peer"]["display_name"] == "Bayo"
    assert lst[0]["unread_count"] == 1 and lst[0]["last_message"]["body"] == "Likewise!"

    # read receipts
    r = await client.post(
        f"/v1/conversations/{cid}/read",
        json={"last_message_id": r1.json()["id"]},
        headers=a["headers"],
    )
    assert r.status_code == 204
    lst = (await client.get("/v1/conversations", headers=a["headers"])).json()["items"]
    assert lst[0]["unread_count"] == 0
    msgs = (await client.get(f"/v1/conversations/{cid}/messages", headers=b["headers"])).json()
    by_id = {m["id"]: m for m in msgs["items"]}
    assert by_id[r1.json()["id"]]["read_at"] and by_id[m1["id"]]["delivered_at"]

    # encrypted at rest, and the outbox carries ids only
    raw = (await session.execute(text("select body from messages"))).scalars().all()
    assert all("great to connect" not in v for v in raw)
    events = (await session.execute(select(OutboxEvent))).scalars().all()
    assert all("great to connect" not in json.dumps(e.payload) for e in events)
    signals = [f.signal for f in (await session.execute(select(MatchFeedback))).scalars()]
    assert signals.count("chat_started") == 1


async def test_block_hides_conversation_for_both(client, session):
    _, _eid, cid, (a, b) = await chat_pair(client)
    await send(client, cid, a, "hello")
    assert (
        await client.post("/v1/blocks", json={"user_id": a["id"]}, headers=b["headers"])
    ).status_code == 204
    for u in (a, b):
        assert (await client.get("/v1/conversations", headers=u["headers"])).json()["items"] == []
        assert (await send(client, cid, u, "still there?")).status_code == 404
        r = await client.get(f"/v1/conversations/{cid}/messages", headers=u["headers"])
        assert r.status_code == 404


async def test_meet_planner_and_reminder(client, session):
    _owner, _eid, cid, (a, b) = await chat_pair(client)
    at = (clock.now() + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    url = f"/v1/conversations/{cid}/meet"
    r = await client.post(
        url, json={"meeting_point": "Rooftop", "at": at.isoformat()}, headers=a["headers"]
    )
    assert r.json()["error"]["code"] == "meet_invalid"  # not one of the event's points
    r = await client.post(
        url,
        json={"meeting_point": "Coffee stand", "at": (at + timedelta(minutes=7)).isoformat()},
        headers=a["headers"],
    )
    assert r.json()["error"]["code"] == "meet_invalid"  # 15 minute slots only
    r = await client.post(
        url, json={"meeting_point": "Coffee stand", "at": at.isoformat()}, headers=a["headers"]
    )
    assert r.status_code == 200 and r.json()["kind"] == "meet_proposal"
    pid = r.json()["id"]
    # the proposer cannot accept their own proposal
    r = await client.post(url, json={"accept_message_id": pid}, headers=a["headers"])
    assert r.status_code == 404
    r = await client.post(url, json={"accept_message_id": pid}, headers=b["headers"])
    assert r.json()["kind"] == "system" and "Coffee stand" in r.json()["body"]
    r = await client.post(url, json={"accept_message_id": pid}, headers=b["headers"])
    assert r.json()["error"]["code"] == "meet_not_open"
    assert [j[0] for j in jobs.pending()] == ["chat.meet_reminder"]
    await jobs.run_pending()
    await chat_jobs.meet_reminder(pid)  # a duplicate run reminds nobody twice
    topics = [e.topic for e in (await session.execute(select(OutboxEvent))).scalars()]
    assert topics.count("chat.meet_reminder") == 1 and "chat.meet_confirmed" in topics
    signals = {f.signal for f in (await session.execute(select(MatchFeedback))).scalars()}
    assert "meet_confirmed" in signals


async def test_chat_died_label(client, session):
    _, _eid, cid, (a, b) = await chat_pair(client)
    await send(client, cid, a, "hello")
    await send(client, cid, b, "hi")
    await chat_jobs.mark_died()
    clock.advance(timedelta(hours=49))
    # Message timestamps come from the app clock, so the conversation is now stale
    await chat_jobs.mark_died()
    await chat_jobs.mark_died()
    signals = [f.signal for f in (await session.execute(select(MatchFeedback))).scalars()]
    assert signals.count("chat_died") == 1


async def test_report_from_chat_attaches_last_messages(client, session):
    owner, _eid, cid, (a, b) = await chat_pair(client)
    await send(client, cid, b, "buy my course")
    r = await client.post(
        "/v1/reports",
        json={"subject_id": b["id"], "reason": "spam", "conversation_id": cid},
        headers=a["headers"],
    )
    assert r.status_code == 204
    await settle()
    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}
    report = (await client.get("/v1/internal/moderation/reports", headers=staff)).json()["items"][0]
    assert [m["body"] for m in report["context"]["messages"]][-1] == "buy my course"


async def test_wingman_assist(client, session):
    _, _eid, cid, (a, b, c) = await chat_pair(client, extra=1)
    await send(client, cid, b, "What are you building?")
    url = "/v1/ai/assist"
    r = await client.post(
        url, json={"conversation_id": cid, "action": "suggest_replies"}, headers=a["headers"]
    )
    assert r.status_code == 200 and len(r.json()["options"]) == 3
    r = await client.post(
        url,
        json={"conversation_id": cid, "action": "rewrite", "text": "yo wanna talk", "tone": "warm"},
        headers=a["headers"],
    )
    assert r.json()["options"] == ["Rewritten: yo wanna talk"]
    # flirt is not a tone; rewrite needs text; strangers cannot use my conversation
    r = await client.post(
        url,
        json={"conversation_id": cid, "action": "rewrite", "text": "hey", "tone": "flirt"},
        headers=a["headers"],
    )
    assert r.status_code == 422
    r = await client.post(
        url, json={"conversation_id": cid, "action": "rewrite"}, headers=a["headers"]
    )
    assert r.status_code == 422
    r = await client.post(
        url, json={"conversation_id": cid, "action": "draft"}, headers=c["headers"]
    )
    assert r.status_code == 404
    # the wingman never sends: no message was created by any of this
    n = len((await session.execute(select(Message).where(Message.kind == "text"))).all())
    assert n == 1

    # streaming draft
    r = await client.post(
        f"{url}/stream", json={"conversation_id": cid, "action": "draft"}, headers=a["headers"]
    )
    assert r.headers["content-type"].startswith("text/event-stream")
    frames = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    assert frames[-1] == {"done": True, "rejected": False}
    assert "".join(f.get("delta", "") for f in frames).startswith("Great to meet you")

    # AI off: a clean 503 the client can degrade on
    await flags.set_flag("ai.task.chat_assist", False)
    flags.clear_cache()
    r = await client.post(
        url, json={"conversation_id": cid, "action": "draft"}, headers=a["headers"]
    )
    assert r.status_code == 503 and r.json()["error"]["code"] == "ai_unavailable"
    await flags.set_flag("ai.task.chat_assist", None)
    flags.clear_cache()


async def test_numbered_spots_spot_me_and_im_here(client, session):
    owner, eid, cid, (a, b, c) = await chat_pair(client, extra=1)
    spots_url = f"/v1/events/{eid}/meeting-spots"
    # the event's two meeting points already are numbered spots
    r = await client.get(spots_url, headers=owner["headers"])
    assert [(s["code"], s["label"]) for s in r.json()] == [
        ("M1", "Coffee stand"),
        ("M2", "Main stage left"),
    ]
    assert (await client.get(spots_url, headers=a["headers"])).status_code == 404
    r = await client.post(
        spots_url, json={"label": "Blue pillar", "hint": "By the exit"}, headers=owner["headers"]
    )
    assert r.status_code == 201 and r.json()["code"] == "M3"

    r = await client.post(spots_url, json={"label": "Blue pillar"}, headers=owner["headers"])
    assert r.json()["error"]["code"] == "spot_exists"
    # switching a spot off keeps its number; a new one never reuses it
    m2 = (await client.get(spots_url, headers=owner["headers"])).json()[1]["id"]
    r = await client.patch(f"{spots_url}/{m2}", json={"active": False}, headers=owner["headers"])
    assert r.json()["active"] is False
    r = await client.post(spots_url, json={"label": "Garden gate"}, headers=owner["headers"])
    assert r.json()["code"] == "M4"
    event = (await client.get(f"/v1/events/{eid}", headers=owner["headers"])).json()
    assert event["meeting_points"] == ["Coffee stand", "Blue pillar", "Garden gate"]

    at = (clock.now() + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    listing = f"/v1/events/{eid}/meet-spots"
    r = await client.get(listing, params={"at": at.isoformat()}, headers=a["headers"])
    assert [s["code"] for s in r.json()] == ["M1", "M3", "M4"]
    assert [s["suggested"] for s in r.json()] == [True, False, False]
    m1 = r.json()[0]["id"]
    assert r.json()[1]["hint"] == "By the exit"

    url = f"/v1/conversations/{cid}/meet"
    r = await client.post(url, json={"spot_id": m2, "at": at.isoformat()}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_invalid"  # switched off
    r = await client.post(
        url,
        json={"spot_id": m1, "at": at.isoformat(), "spot_me": "Red jacket, by the menu"},
        headers=a["headers"],
    )
    assert r.status_code == 200 and "M1 · Coffee stand" in r.json()["body"]
    pid = r.json()["id"]
    assert r.json()["payload"]["spot_me"] == {a["id"]: "Red jacket, by the menu"}
    # that spot now has a meeting at that time, so a quieter one is suggested
    r = await client.get(listing, params={"at": at.isoformat()}, headers=c["headers"])
    assert [(s["code"], s["busy"], s["suggested"]) for s in r.json()] == [
        ("M1", "some", False),
        ("M3", "quiet", True),
        ("M4", "quiet", False),
    ]
    assert all(
        set(s) == {"id", "number", "code", "label", "hint", "busy", "suggested"} for s in r.json()
    )

    status = f"{url}/{pid}/status"
    # nobody outside the chat can touch or read the meet-up
    r = await client.post(status, json={"arrived": True}, headers=c["headers"])
    assert r.status_code == 404
    # "I'm here" needs a confirmed meeting
    r = await client.post(status, json={"arrived": True}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_now"
    r = await client.post(
        url, json={"accept_message_id": pid, "spot_me": "Green cap"}, headers=b["headers"]
    )
    assert "M1 · Coffee stand" in r.json()["body"]
    # ... and it is too early an hour before
    r = await client.post(status, json={"arrived": True}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_now"
    r = await client.post(status, json={"spot_me": "Now by the door"}, headers=a["headers"])
    assert r.json()["payload"]["spot_me"] == {a["id"]: "Now by the door", b["id"]: "Green cap"}

    clock.advance(at - clock.now() - timedelta(minutes=5))
    await settle()
    r = await client.post(status, json={"arrived": True}, headers=a["headers"])
    assert list(r.json()["payload"]["arrived"]) == [a["id"]]
    r = await client.post(status, json={"arrived": True}, headers=a["headers"])  # second tap
    assert r.status_code == 200
    await settle()
    topics = [e.topic for e in (await session.execute(select(OutboxEvent))).scalars()]
    assert topics.count("chat.meet_arrived") == 1
    notes = (await client.get("/v1/notifications", headers=b["headers"])).json()["items"]
    assert any("is at M1 · Coffee stand" in n["body"] for n in notes)
    notes = (await client.get("/v1/notifications", headers=a["headers"])).json()["items"]
    assert not any("is at M1" in n["body"] for n in notes)

    # the "how to spot me" lines are erased a day after the meeting; the meet-up stays
    clock.advance(timedelta(days=1, hours=1))
    await chat_jobs.retention()
    r = await client.post(status, json={"spot_me": "Too late"}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_open"
    msgs = (await client.get(f"/v1/conversations/{cid}/messages", headers=b["headers"])).json()
    card = next(m for m in msgs["items"] if m["id"] == pid)
    assert "spot_me" not in card["payload"] and card["payload"]["status"] == "accepted"


async def test_two_way_location_sharing(client, session, monkeypatch):
    from app.modules.chat import location
    from app.modules.realtime import public as realtime

    sent: list[tuple[str, str, dict]] = []

    async def capture(user_id, kind, payload):
        sent.append((user_id, kind, payload))

    monkeypatch.setattr(realtime, "publish_user", capture)
    _owner, _eid, cid, (a, b, c) = await chat_pair(client, extra=1)
    at = (clock.now() + timedelta(hours=1)).replace(minute=30, second=0, microsecond=0)
    url = f"/v1/conversations/{cid}/meet"
    pid = (
        await client.post(
            url, json={"meeting_point": "Coffee stand", "at": at.isoformat()}, headers=a["headers"]
        )
    ).json()["id"]
    share, pos = f"{url}/{pid}/sharing", f"{url}/{pid}/position"
    here = {"lat": 6.4300, "lng": 3.4200, "accuracy_m": 8}
    north_east = {"lat": 6.4303, "lng": 3.4203, "accuracy_m": 8}  # about 47 m away

    # not before the meeting is confirmed
    r = await client.post(share, json={"on": True}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_now"
    await client.post(url, json={"accept_message_id": pid}, headers=b["headers"])
    # nobody outside the meet-up, and no position before the person turns sharing on
    assert (await client.post(share, json={"on": True}, headers=c["headers"])).status_code == 404
    assert (await client.get(pos, headers=c["headers"])).status_code == 404
    r = await client.post(pos, json=here, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_now"

    r = await client.post(share, json={"on": True}, headers=a["headers"])
    assert r.json() == {
        "me_sharing": True,
        "peer_sharing": False,
        "distance_m": None,
        "direction": None,
        "rough": False,
        "age_s": None,
    }
    await settle()
    topics = [e.topic for e in (await session.execute(select(OutboxEvent))).scalars()]
    assert topics.count("chat.meet_sharing") == 1
    # too early: positions open 30 minutes before the meeting
    r = await client.post(pos, json=here, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_now"
    clock.advance(at - clock.now() - timedelta(minutes=10))
    # only one side has said yes: nothing is stored
    r = await client.post(pos, json=here, headers=a["headers"])
    assert r.status_code == 200 and r.json()["distance_m"] is None
    assert await location.load(pid, a["id"]) is None

    await client.post(share, json={"on": True}, headers=b["headers"])
    await client.post(pos, json=here, headers=a["headers"])
    sent.clear()
    r = await client.post(pos, json=north_east, headers=b["headers"])
    assert r.json()["distance_m"] == 50 and r.json()["direction"] == "SW"
    assert r.json()["rough"] is False
    nearby = [p for u, k, p in sent if k == "meet.nearby"]
    assert [u for u, k, _ in sent if k == "meet.nearby"] == [a["id"]]
    assert nearby[0]["direction"] == "NE" and nearby[0]["distance_m"] == 50
    assert not {"lat", "lng"} & set(nearby[0])  # never coordinates
    r = await client.get(pos, headers=a["headers"])
    assert r.json()["direction"] == "NE"
    # nothing about positions reaches the database
    msgs = (await client.get(f"/v1/conversations/{cid}/messages", headers=a["headers"])).json()
    assert "lat" not in json.dumps(msgs) and "6.43" not in json.dumps(msgs)

    # turning it off deletes my position at once
    await client.post(share, json={"on": False}, headers=b["headers"])
    assert await location.load(pid, b["id"]) is None
    assert (await client.get(pos, headers=a["headers"])).json()["peer_sharing"] is False
    await client.post(share, json={"on": True}, headers=b["headers"])
    await client.post(pos, json=north_east, headers=b["headers"])

    # once both say "I'm here", sharing ends for good
    status = f"{url}/{pid}/status"
    await client.post(status, json={"arrived": True}, headers=a["headers"])
    await client.post(status, json={"arrived": True}, headers=b["headers"])
    assert await location.load(pid, a["id"]) is None and await location.load(pid, b["id"]) is None
    r = await client.get(pos, headers=a["headers"])
    assert r.json()["me_sharing"] is False and r.json()["distance_m"] is None
    r = await client.post(share, json={"on": True}, headers=a["headers"])
    assert r.json()["error"]["code"] == "meet_not_open"
