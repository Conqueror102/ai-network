from sqlalchemy import select

from app.adapters import factory
from app.core import jobs
from app.modules.profiles.models import EventProfile, Goal
from tests.helpers import check_in, join, make_event, sign_up


async def test_profile_goal_parse_and_embed(client, session):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    eid = event["id"]
    a = await sign_up(client, name="Ada")
    base = f"/v1/events/{eid}"
    r = await client.put(f"{base}/profile", json={"display_name": "Ada"}, headers=a["headers"])
    assert r.json()["error"]["code"] == "checkin_required"
    await check_in(client, owner, eid, a)
    assert (await client.get(f"{base}/room", headers=a["headers"])).json()["my_profile"] is None
    r = await client.put(
        f"{base}/profile",
        json={
            "display_name": "Ada",
            "headline": "CTO at Paylane",
            "offer_text": "I can offer fintech engineering advice",
        },
        headers=a["headers"],
    )
    assert r.status_code == 200 and r.json()["visibility"] == "directory"
    r = await client.put(
        f"{base}/profile", json={"display_name": "Ada", "visibility": "radar"}, headers=a["headers"]
    )
    assert r.json()["error"]["code"] == "radar_requires_photo"

    r = await client.post(
        f"{base}/goals/parse",
        json={"text": "I'm hiring fintech engineers. I can offer equity"},
        headers=a["headers"],
    )
    draft = r.json()["goal"]
    assert draft["intent"] == "hire" and draft["target"]["industries"] == ["fintech"]
    assert (await session.execute(select(Goal))).first() is None  # parse never saves

    body = {k: draft[k] for k in ("intent", "target", "offer", "raw_input", "priority")}
    r = await client.post(f"{base}/goals", json=body, headers=a["headers"])
    assert r.status_code == 201
    gid = r.json()["id"]
    r = await client.post(f"{base}/goals", json=body, headers=a["headers"])
    assert r.json()["error"]["code"] == "goal_priority_taken"

    assert [j[0] for j in jobs.pending()] == ["profiles.embed"]  # debounced into one job
    await jobs.run_pending()
    session.expire_all()
    goal = (await session.execute(select(Goal))).scalar_one()
    profile = (await session.execute(select(EventProfile))).scalar_one()
    assert len(goal.ask_embedding) == 1024 and goal.embedding_model == "fake-bow-v1"
    assert profile.profile_embedding is not None

    # only the owner can edit a goal
    other = await sign_up(client)
    assert (
        await client.patch(f"/v1/goals/{gid}", json={"offer": "x"}, headers=other["headers"])
    ).status_code == 404
    assert (await client.delete(f"/v1/goals/{gid}", headers=a["headers"])).status_code == 204
    room = (await client.get(f"{base}/room", headers=a["headers"])).json()
    assert room["goals"] == [] and room["checked_in_count"] == 1


async def test_goal_parse_falls_back_to_manual_when_ai_down(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    a = await join(client, owner, event["id"], name="Ada")
    fake = factory.llm_providers()["fake"]
    fake.down = True
    try:
        r = await client.post(
            f"/v1/events/{event['id']}/goals/parse",
            json={"text": "hiring engineers"},
            headers=a["headers"],
        )
        assert r.status_code == 200 and r.json() == {"goal": None, "manual": True}
    finally:
        fake.reset()


async def test_goal_limit_and_rejected_content(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    goal = {"intent": "meet"}
    a = await join(client, owner, event["id"], name="Ada", goals=[goal, goal, goal])
    r = await client.post(
        f"/v1/events/{event['id']}/goals",
        json={"intent": "meet", "priority": 3},
        headers=a["headers"],
    )
    assert r.json()["error"]["code"] == "goal_limit_reached"
    r = await client.put(
        f"/v1/events/{event['id']}/profile",
        json={"display_name": "Ada", "offer_text": "send me money now"},
        headers=a["headers"],
    )
    assert r.json()["error"]["code"] == "content_rejected"


async def test_directory_visibility_and_reciprocity(client):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    eid = event["id"]
    ada = await join(client, owner, eid, name="Ada", headline="Fintech CTO")
    bola = await join(client, owner, eid, name="Bola", headline="Designer")
    ghost = await join(client, owner, eid, name="Ghost", visibility="hidden")
    url = f"/v1/events/{eid}/directory"
    names = [
        i["display_name"] for i in (await client.get(url, headers=ada["headers"])).json()["items"]
    ]
    assert names == ["Bola"]  # not me, not hidden
    r = await client.get(url, headers=ghost["headers"])
    assert r.json()["error"]["code"] == "directory_requires_visibility"
    r = await client.get(f"{url}?q=design", headers=ada["headers"])
    assert [i["display_name"] for i in r.json()["items"]] == ["Bola"]
    r = await client.get(f"/v1/events/{eid}/profiles/{ghost['id']}", headers=ada["headers"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_visible"
    card = (
        await client.get(f"/v1/events/{eid}/profiles/{bola['id']}", headers=ada["headers"])
    ).json()
    assert set(card) == {"user_id", "display_name", "photo_url", "headline", "offer_text"}
