from sqlalchemy import select

from app.core import jobs, outbox
from app.modules.matching import service
from app.modules.matching.models import MatchFeedback, MatchScore
from app.modules.safety.models import Block
from tests.helpers import join, make_event, sign_up

SELL = {
    "intent": "sell",
    "target": {"industries": ["events"], "roles": ["organizer"]},
    "raw_input": "sell networking platform to conference organizers events",
    "offer": "AI networking platform for conference events",
}
BUY = {
    "intent": "buy",
    "target": {},
    "raw_input": "buy tools platform to improve my conference events",
    "offer": "I organize DevCon",
}


async def settle():
    for _ in range(4):
        await outbox.drain()
        await jobs.run_pending()


async def room(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    victor = await join(
        client,
        owner,
        eid,
        name="Victor",
        headline="Founder building event tech",
        offer="AI networking platform for conference events",
        goals=[SELL],
    )
    sara = await join(
        client,
        owner,
        eid,
        name="Sara",
        headline="Conference organizer, events",
        offer="I organize DevCon conference events",
        goals=[BUY],
        role_title="Organizer",
        industry="events",
    )
    await settle()
    return owner, eid, victor, sara


async def feed(client, eid, user):
    r = await client.get(f"/v1/events/{eid}/matches", headers=user["headers"])
    assert r.status_code == 200, r.text
    return r.json()


async def test_feed_shows_mutual_match_with_grounded_why(client, session):
    _owner, eid, victor, sara = await room(client)
    f = await feed(client, eid, victor)
    assert f["warming_up"] is True and f["computed_at"]
    card = f["items"][0]
    assert card["user_id"] == sara["id"] and card["display_name"] == "Sara"
    assert card["score_bucket"] == "high" and card["wildcard"] is False
    assert card["matched_chips"][:2] == ["organizer", "events"]
    assert card["why"] == "You match on organizer, events, buying."
    # raw scores and embeddings never leave the server
    assert not {"score", "score_a", "components", "fit_ab"} & set(card)
    # the other side sees the pair too (fan-out refreshed her feed)
    g = await feed(client, eid, sara)
    assert [c["user_id"] for c in g["items"]] == [victor["id"]]
    row = (await session.execute(select(MatchScore))).scalar_one()
    assert row.components["intent_bonus_ab"] == 0.25 and row.components["matched"]


async def test_feed_exclusions_hidden_blocked_skipped(client, session):
    owner, eid, victor, sara = await room(client)
    ghost = await join(
        client,
        owner,
        eid,
        name="Ghost",
        headline="Conference organizer, events",
        offer="I organize conference events",
        goals=[BUY],
        visibility="hidden",
    )
    tola = await join(
        client,
        owner,
        eid,
        name="Tola",
        headline="Conference organizer, events",
        offer="I run conference events",
        goals=[BUY],
    )
    await settle()
    ids = [c["user_id"] for c in (await feed(client, eid, victor))["items"]]
    assert set(ids) == {sara["id"], tola["id"]}  # hidden people are never candidates
    assert (await feed(client, eid, ghost))["items"] == []  # and get no feed themselves

    # a block takes effect on the very next read, in both directions, before any recompute
    session.add(Block(user_id=tola["id"], blocked_id=victor["id"]))
    await session.commit()
    assert [c["user_id"] for c in (await feed(client, eid, victor))["items"]] == [sara["id"]]
    assert victor["id"] not in [c["user_id"] for c in (await feed(client, eid, tola))["items"]]

    # skip hides, logs feedback with frozen components, and survives recompute
    r = await client.post(f"/v1/events/{eid}/matches/{sara['id']}/skip", headers=victor["headers"])
    assert r.status_code == 204
    await client.post(f"/v1/events/{eid}/matches/{sara['id']}/skip", headers=victor["headers"])
    fb = (await session.execute(select(MatchFeedback))).scalars().all()
    assert len(fb) == 1 and fb[0].signal == "feed_skip" and fb[0].components["goal_score"] > 0
    assert (await feed(client, eid, victor))["items"] == []
    await settle()
    assert (await feed(client, eid, victor))["items"] == []
    # skipping is one-way: Sara still sees Victor
    assert victor["id"] in [c["user_id"] for c in (await feed(client, eid, sara))["items"]]
    # cannot skip someone you cannot see
    r = await client.post(f"/v1/events/{eid}/matches/{ghost['id']}/skip", headers=victor["headers"])
    assert r.status_code == 404


async def test_money_never_ranks(client, session):
    """00 §4: premium status must not move anyone in anyone's feed."""
    owner, eid, victor, sara = await room(client)
    tola = await join(
        client,
        owner,
        eid,
        name="Tola",
        headline="Conference organizer",
        offer="I run meetups",
        goals=[BUY],
    )
    await settle()
    before = [c["user_id"] for c in (await feed(client, eid, victor))["items"]]
    assert before[0] == sara["id"] and tola["id"] in before
    from datetime import timedelta

    from sqlalchemy import update

    from app.core import clock
    from app.modules.identity.models import User

    await session.execute(
        update(User)
        .where(User.id == tola["id"])
        .values(premium_until=clock.now() + timedelta(days=30))
    )
    await session.commit()
    await service.compute_for_user(session, eid, victor["id"])
    await session.commit()
    assert [c["user_id"] for c in (await feed(client, eid, victor))["items"]] == before


async def test_matching_config_is_staff_only_and_tunable(client, session):
    owner, eid, victor, _sara = await room(client)
    r = await client.get("/v1/internal/matching/config", headers=victor["headers"])
    assert r.status_code == 404
    from app.core.security.jwt import issue_access_token

    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}
    r = await client.put(
        "/v1/internal/matching/config", json={"values": {"nope": 1}}, headers=staff
    )
    assert r.status_code == 422
    r = await client.put(
        "/v1/internal/matching/config", json={"values": {"min_score": 0.99}}, headers=staff
    )
    assert r.status_code == 200 and r.json()["values"]["min_score"] == 0.99
    await service.compute_for_user(session, eid, victor["id"])
    await session.commit()
    assert (await feed(client, eid, victor))["items"] == []  # nothing clears the new floor
    service.clear_config_cache()
