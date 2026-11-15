from sqlalchemy import inspect, select

from app.core import flags
from app.modules.ads import service as ads_service
from app.modules.ads.models import AdImpressionDaily
from tests.helpers import join, make_event, sign_up


async def setup(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    r = await client.post(
        f"/v1/events/{eid}/sponsors",
        json={
            "name": "Paylane",
            "tagline": "Payments for Africa",
            "url": "https://paylane.example",
        },
        headers=owner["headers"],
    )
    assert r.status_code == 201 and r.json()["status"] == "active", r.text
    sid = r.json()["id"]
    r = await client.post(
        f"/v1/events/{eid}/ads",
        json={"sponsor_id": sid, "title": "Visit booth 4", "body": "Free coffee all day"},
        headers=owner["headers"],
    )
    assert r.status_code == 201, r.text
    return owner, eid, a, sid, r.json()["id"]


async def test_sponsored_tile_label_counters_and_caps(client, session, monkeypatch):
    owner, eid, a, sid, pid = await setup(client)
    tile = (await client.get(f"/v1/events/{eid}/sponsored", headers=a["headers"])).json()["tile"]
    assert tile == {
        "placement_id": pid,
        "label": "Sponsored",
        "sponsor_name": "Paylane",
        "title": "Visit booth 4",
        "body": "Free coffee all day",
        "cta_url": None,
    }
    # the label is not an input anywhere: organizers cannot send it
    r = await client.post(
        f"/v1/events/{eid}/ads",
        json={"sponsor_id": sid, "title": "x", "label": "Recommended"},
        headers=owner["headers"],
    )
    assert r.status_code == 422
    r = await client.post(f"/v1/events/{eid}/sponsored/{pid}/tap", headers=a["headers"])
    assert r.status_code == 204
    # attendees cannot manage ads; organizers of other events cannot touch these
    assert (await client.get(f"/v1/events/{eid}/ads", headers=a["headers"])).status_code == 404
    other = await sign_up(client)
    other_eid = (await make_event(client, other, name="Other"))["id"]
    r = await client.post(
        f"/v1/events/{other_eid}/ads",
        json={"sponsor_id": sid, "title": "Hijack"},
        headers=other["headers"],
    )
    assert r.status_code == 404
    r = await client.get(f"/v1/events/{other_eid}/sponsors/{sid}/report", headers=other["headers"])
    assert r.status_code == 404

    # frequency cap per attendee per day, then the tile disappears for them
    monkeypatch.setattr(ads_service, "DAILY_CAP", 2)
    await client.get(f"/v1/events/{eid}/sponsored", headers=a["headers"])
    r = await client.get(f"/v1/events/{eid}/sponsored", headers=a["headers"])
    assert r.json()["tile"] is None
    # kill switch per event
    b = await join(client, owner, eid, name="Bayo")
    await flags.set_flag(f"sponsor.surfaces.{eid}", False)
    flags.clear_cache()
    r = await client.get(f"/v1/events/{eid}/sponsored", headers=b["headers"])
    assert r.json()["tile"] is None
    await flags.set_flag(f"sponsor.surfaces.{eid}", None)
    flags.clear_cache()


async def test_sponsor_text_is_screened(client, session):
    owner, eid, _a, sid, _pid = await setup(client)
    r = await client.post(
        f"/v1/events/{eid}/sponsors",
        json={"name": "Scam Co", "tagline": "double your bitcoin giveaway"},
        headers=owner["headers"],
    )
    assert r.json()["error"]["code"] == "sponsor_text_rejected"
    # screen unavailable: saved but held, and never shown until staff release it
    await flags.set_flag("ai.task.safety_screen", False)
    flags.clear_cache()
    r = await client.post(
        f"/v1/events/{eid}/ads",
        json={"sponsor_id": sid, "title": "Unscreened"},
        headers=owner["headers"],
    )
    assert r.json()["status"] == "held"
    held = r.json()["id"]
    r = await client.post(
        f"/v1/events/{eid}/ads/{held}/status", json={"status": "active"}, headers=owner["headers"]
    )
    assert r.status_code == 404  # an organizer cannot release their own held content
    await flags.set_flag("ai.task.safety_screen", None)
    flags.clear_cache()


async def test_sponsor_aggregates_only(client, session):
    """08 §6: sponsors and organizers get counts, never who."""
    owner, eid, a, sid, pid = await setup(client)
    b = await join(client, owner, eid, name="Bayo")
    for u in (a, b, a):
        await client.get(f"/v1/events/{eid}/sponsored", headers=u["headers"])
    await client.post(f"/v1/events/{eid}/sponsored/{pid}/tap", headers=b["headers"])
    report = (
        await client.get(f"/v1/events/{eid}/sponsors/{sid}/report", headers=owner["headers"])
    ).json()
    assert (report["impressions"], report["taps"]) == (3, 1)
    blob = str(report)
    assert a["id"] not in blob and b["id"] not in blob and "usr_" not in blob

    # structurally: nowhere to put a user id in the sponsor and ad tables
    def columns(sync_conn):
        insp = inspect(sync_conn)
        return {
            t: {c["name"] for c in insp.get_columns(t)}
            for t in ("sponsors", "ad_placements", "ad_impressions_daily")
        }

    cols = await (await session.connection()).run_sync(columns)
    for table, names in cols.items():
        assert not {n for n in names if "user" in n}, table
    rows = (await session.execute(select(AdImpressionDaily))).scalars().all()
    assert len(rows) == 1
    # and the sponsors module exposes nothing that returns a person
    from app.modules.sponsors import public

    assert set(public.__all__) == {"SponsorInfo", "SponsorTextRejected", "get_info", "screen_text"}
