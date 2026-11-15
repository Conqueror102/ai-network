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
