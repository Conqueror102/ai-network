"""Discovery beyond mutual matches: a developer wants to meet a lawyer whose own goals
have nothing to do with developers. The lawyer "would not mind", so the developer must
be able to find them and wave, and the lawyer still gets the final say."""

import pytest

from app.adapters import factory
from app.core import jobs, outbox
from app.core.security.jwt import issue_access_token
from app.modules.matching import service as matching
from tests.helpers import join, make_event, sign_up


async def settle():
    for _ in range(4):
        await outbox.drain()
        await jobs.run_pending()


@pytest.fixture
async def room(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    dev = await join(
        client,
        owner,
        eid,
        name="Dayo",
        headline="Backend developer",
        offer="python api engineering",
        role_title="Software Engineer",
        industry="Software",
        goals=[
            {
                "intent": "meet",
                "target": {"roles": ["lawyer"]},
                "raw_input": "meet a startup lawyer for legal contracts advice",
            }
        ],
    )
    lawyer = await join(
        client,
        owner,
        eid,
        name="Lola",
        headline="Partner at Lex Chambers",
        offer="legal contracts advice for a startup",
        role_title="Lawyer",
        industry="Legal",
        company="Lex Chambers",
        goals=[
            {
                "intent": "sell",
                "target": {"roles": ["founder"]},
                "raw_input": "find fintech founders raising funding as clients",
            }
        ],
    )
    chef = await join(
        client, owner, eid, name="Kunle", headline="Private chef", offer="catering for dinners"
    )
    await settle()
    return {"owner": owner, "eid": eid, "dev": dev, "lawyer": lawyer, "chef": chef}


async def names(client, url, user, **params):
    r = await client.get(url, params=params, headers=user["headers"])
    assert r.status_code == 200, r.text
    return [i["display_name"] for i in r.json()["items"]]


async def set_open(client, eid, user, name, value, **card):
    """PUT replaces the whole card, so the headline and offer are sent again."""
    r = await client.put(
        f"/v1/events/{eid}/profile",
        json={"display_name": name, "open_to_all": value, **card},
        headers=user["headers"],
    )
    assert r.status_code == 200, r.text
    assert r.json()["open_to_all"] is value
    await settle()


async def test_directory_filters_and_wider_keyword_search(client, room):
    eid, dev = room["eid"], room["dev"]
    url = f"/v1/events/{eid}/directory"
    assert sorted(await names(client, url, dev)) == ["Kunle", "Lola"]
    # the old search only read name and headline: "lawyer" is in neither for Lola
    assert await names(client, url, dev, q="lawyer") == ["Lola"]
    assert await names(client, url, dev, q="contracts") == ["Lola"]  # offer text
    assert await names(client, url, dev, role="lawyer") == ["Lola"]
    assert await names(client, url, dev, industry="legal") == ["Lola"]
    assert await names(client, url, dev, company="lex") == ["Lola"]
    assert await names(client, url, dev, looking_for="sell") == ["Lola"]
    assert await names(client, url, dev, looking_for="hire") == []
    assert await names(client, url, dev, role="lawyer", industry="software") == []  # AND
    r = await client.get(url, params={"looking_for": "world peace"}, headers=dev["headers"])
    assert r.status_code == 422

    card = (await client.get(url, params={"role": "lawyer"}, headers=dev["headers"])).json()[
        "items"
    ][0]
    assert card["role_title"] == "Lawyer" and card["company"] == "Lex Chambers"
    assert card["looking_for"] == ["sell"]
    # still nothing private or location-like on a directory row
    assert set(card) == {
        "user_id",
        "display_name",
        "photo_url",
        "headline",
        "offer_text",
        "role_title",
        "company",
        "industry",
        "looking_for",
    }


async def test_smart_search_finds_people_by_meaning(client, room):
    eid, dev = room["eid"], room["dev"]
    url = f"/v1/events/{eid}/directory/search"
    r = await client.get(url, params={"q": "someone for legal contracts"}, headers=dev["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "smart"
    assert [i["display_name"] for i in body["items"]] == ["Lola"]  # the chef is noise
    assert "score" not in body["items"][0]  # raw scores never leave the server

    # with embeddings down it degrades to a keyword match instead of failing
    emb = factory.embeddings()
    emb.fail = True
    try:
        r = await client.get(url, params={"q": "contracts"}, headers=dev["headers"])
    finally:
        emb.fail = False
    assert r.status_code == 200 and r.json()["mode"] == "keyword"
    assert [i["display_name"] for i in r.json()["items"]] == ["Lola"]

    assert (await client.get(url, params={"q": "ab"}, headers=dev["headers"])).status_code == 422
    assert (await client.get(url, params={"q": "lawyer"})).status_code == 401


async def test_asked_for_row_shows_one_sided_fits(client, session, room):
    eid, dev, lawyer, owner = room["eid"], room["dev"], room["lawyer"], room["owner"]
    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}
    try:
        # a strict mutual floor, so the lawyer cannot reach the developer's main feed
        r = await client.put(
            "/v1/internal/matching/config", json={"values": {"min_score": 0.9}}, headers=staff
        )
        assert r.status_code == 200, r.text
        await matching.compute_for_user(session, eid, dev["id"])
        await session.commit()
        feed = (await client.get(f"/v1/events/{eid}/matches", headers=dev["headers"])).json()
        assert feed["items"] == []
        asked = feed["asked_for"]
        assert [c["display_name"] for c in asked] == ["Lola"]
        assert asked[0]["why"] == "Fits what you are looking for."
        assert "lawyer" in asked[0]["matched_chips"]
        assert "score" not in asked[0] and "score_bucket" not in asked[0]

        # the lawyer does not get the developer pushed at them in return
        await matching.compute_for_user(session, eid, lawyer["id"])
        await session.commit()
        theirs = (await client.get(f"/v1/events/{eid}/matches", headers=lawyer["headers"])).json()
        assert [c["display_name"] for c in theirs["asked_for"]] == []

        # the developer waves; the lawyer accepts; the row empties
        r = await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": lawyer["id"], "source": "directory"},
            headers=dev["headers"],
        )
        assert r.status_code == 201, r.text
        feed = (await client.get(f"/v1/events/{eid}/matches", headers=dev["headers"])).json()
        assert feed["asked_for"] == []
        r = await client.post(
            f"/v1/waves/{r.json()['id']}/respond",
            json={"action": "accept"},
            headers=lawyer["headers"],
        )
        assert r.status_code == 200 and r.json()["conversation_id"]
    finally:
        matching.clear_config_cache()


async def test_closed_profile_is_only_reachable_through_a_match(client, session, room):
    eid, dev, lawyer, owner = room["eid"], room["dev"], room["lawyer"], room["owner"]
    await set_open(
        client,
        eid,
        lawyer,
        "Lola",
        False,
        headline="Partner at Lex Chambers",
        offer_text="legal contracts advice for a startup",
    )
    url = f"/v1/events/{eid}/directory"
    assert await names(client, url, dev) == ["Kunle"]
    assert await names(client, url, dev, role="lawyer") == []
    r = await client.get(f"{url}/search", params={"q": "legal contracts"}, headers=dev["headers"])
    assert r.json()["items"] == []

    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}
    try:
        await client.put(
            "/v1/internal/matching/config", json={"values": {"min_score": 0.9}}, headers=staff
        )
        await matching.compute_for_user(session, eid, dev["id"])
        await session.commit()
        feed = (await client.get(f"/v1/events/{eid}/matches", headers=dev["headers"])).json()
        assert feed["items"] == [] and feed["asked_for"] == []
        # not matched, so a wave is refused with the same answer as "not at this event"
        r = await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": lawyer["id"], "source": "directory"},
            headers=dev["headers"],
        )
        assert r.status_code == 404, r.text
        stranger = await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": "usr_does_not_exist", "source": "directory"},
            headers=dev["headers"],
        )
        assert stranger.json()["error"]["code"] == r.json()["error"]["code"]

        # the closed person can still reach out, and then the other side may answer
        r = await client.post(
            f"/v1/events/{eid}/waves",
            json={"to_user": dev["id"], "source": "directory"},
            headers=lawyer["headers"],
        )
        assert r.status_code == 201, r.text
        r = await client.post(
            f"/v1/waves/{r.json()['id']}/respond",
            json={"action": "accept"},
            headers=dev["headers"],
        )
        assert r.status_code == 200, r.text
    finally:
        matching.clear_config_cache()


async def test_closed_profile_stays_in_mutual_feeds(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    goal = {"intent": "meet", "target": {}, "raw_input": "meet fintech payments founders"}
    kw = {"headline": "Fintech payments founder", "offer": "fintech payments", "goals": [goal]}
    a = await join(client, owner, eid, name="Ada", **kw)
    b = await join(client, owner, eid, name="Bayo", **kw)
    await settle()
    await set_open(client, eid, b, "Bayo", False, headline=kw["headline"], offer_text=kw["offer"])
    await matching.compute_for_user(session, eid, a["id"])
    await session.commit()
    feed = (await client.get(f"/v1/events/{eid}/matches", headers=a["headers"])).json()
    assert [c["display_name"] for c in feed["items"]] == ["Bayo"]
    r = await client.post(
        f"/v1/events/{eid}/waves",
        json={"to_user": b["id"], "source": "match_feed"},
        headers=a["headers"],
    )
    assert r.status_code == 201, r.text
