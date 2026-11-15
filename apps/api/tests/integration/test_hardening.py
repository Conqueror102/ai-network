"""B11: audit trail, data export, retention and hard delete."""

import json
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core import clock, jobs, outbox
from app.core.audit import AuditLog
from app.core.security.jwt import issue_access_token
from app.modules.identity import jobs as identity_jobs
from app.modules.identity.models import User
from app.modules.profiles.models import EventProfile
from app.modules.waves import jobs as wave_jobs
from app.modules.waves.models import Wave
from tests.helpers import join, make_event, sign_up


async def settle():
    for _ in range(4):
        await outbox.drain()
        await jobs.run_pending()


def staff_headers(user):
    return {"Authorization": f"Bearer {issue_access_token(user['id'], staff=True)}"}


async def pair(client):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada", share_phone=True)
    b = await join(client, owner, eid, name="Bayo", share_phone=True)
    await settle()
    return owner, eid, a, b


async def wave(client, eid, frm, to, note=None):
    body = {"to_user": to["id"], "source": "directory"}
    if note:
        body["note"] = note
    r = await client.post(f"/v1/events/{eid}/waves", json=body, headers=frm["headers"])
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_export_is_my_data_and_nobody_elses(client, session):
    owner, eid, a, b = await pair(client)
    wid = await wave(client, eid, a, b, note="Loved your talk")
    cid = (
        await client.post(
            f"/v1/waves/{wid}/respond", json={"action": "accept"}, headers=b["headers"]
        )
    ).json()["conversation_id"]
    await settle()
    for user, body in ((a, "Hello from Ada"), (b, "Secret reply from Bayo")):
        r = await client.post(
            f"/v1/conversations/{cid}/messages", json={"body": body}, headers=user["headers"]
        )
        assert r.status_code == 201, r.text

    r = await client.get("/v1/me/export", headers=a["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["account"]["phone"] == a["phone"]
    assert data["event_profiles"][0]["display_name"] == "Ada"
    assert data["waves"]["sent"][0]["note"] == "Loved your talk"
    mine = [m["body"] for c in data["conversations"] for m in c["my_messages"]]
    assert mine == ["Hello from Ada"]
    raw = json.dumps(data)
    assert "Secret reply from Bayo" not in raw  # the other person's words are theirs
    assert b["phone"] not in raw  # and so are their contact details

    # exports are audited, and only staff can read the trail
    assert (await client.get("/v1/internal/audit", headers=a["headers"])).status_code == 404
    trail = await client.get(
        "/v1/internal/audit", params={"action": "privacy.export"}, headers=staff_headers(owner)
    )
    assert [e["actor_id"] for e in trail.json()["items"]] == [a["id"]]
    assert (await client.get("/v1/me/export")).status_code == 401


async def test_export_never_reveals_a_decline(client, session):
    _, eid, a, b = await pair(client)
    wid = await wave(client, eid, a, b)
    r = await client.post(
        f"/v1/waves/{wid}/respond", json={"action": "not_now"}, headers=b["headers"]
    )
    assert r.status_code in (200, 204), r.text
    sent = (await client.get("/v1/me/export", headers=a["headers"])).json()["waves"]["sent"]
    assert [w["status"] for w in sent] == ["pending"]


async def test_export_is_rate_limited(client):
    u = await sign_up(client)
    codes = [
        (await client.get("/v1/me/export", headers=u["headers"])).status_code for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


async def test_staff_actions_are_audited_atomically(client, session):
    owner = await sign_up(client)
    staff = staff_headers(owner)
    # a failed action leaves no audit row behind
    r = await client.post("/v1/internal/billing/invoices/inv_missing/refund", headers=staff)
    assert r.status_code == 404
    assert (await session.scalars(select(AuditLog))).all() == []

    r = await client.put(
        "/v1/internal/matching/config", json={"values": {"feed_size": 6}}, headers=staff
    )
    assert r.status_code == 200, r.text
    rows = (await session.scalars(select(AuditLog))).all()
    assert [(x.action, x.actor_role, x.actor_id) for x in rows] == [
        ("matching.config_set", "staff", owner["id"])
    ]
    assert rows[0].meta == {"keys": ["feed_size"]}


async def test_organizer_actions_are_audited_with_their_org(client, session):
    owner = await sign_up(client)
    event = await make_event(client, owner)
    rows = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    assert rows[-1].action == "event.status_set"
    assert (rows[-1].org_id, rows[-1].event_id) == (owner["org_id"], event["id"])
    assert rows[-1].actor_role == "organizer"


async def test_audit_log_is_append_only(client, session):
    owner = await sign_up(client)
    await make_event(client, owner)
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(text("UPDATE audit_log SET action = 'x'"))
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(text("DELETE FROM audit_log"))


async def test_deleted_account_is_purged_after_30_days(client, session):
    _, eid, a, b = await pair(client)
    wid = await wave(client, eid, a, b, note="Coffee?")
    assert (await client.delete("/v1/me", headers=a["headers"])).status_code == 204
    await settle()

    clock.advance(timedelta(days=29))
    assert await identity_jobs.purge_deleted_users() == 0  # still inside the grace period
    clock.advance(timedelta(days=2))
    assert await identity_jobs.purge_deleted_users() == 1
    await settle()

    session.expire_all()
    u = await session.get(User, a["id"])
    assert u is not None and u.purged_at is not None  # tombstone stays for chat history
    assert (u.phone, u.email, u.display_name, u.real_name, u.bio) == (None,) * 5
    profiles = await session.scalars(select(EventProfile).where(EventProfile.user_id == a["id"]))
    assert profiles.all() == []
    w = await session.get(Wave, wid)
    assert w is not None and w.card == {} and w.note is None
    assert await identity_jobs.purge_deleted_users() == 0  # idempotent
    # the phone number is free again
    again = await sign_up(client, phone=a["phone"])
    assert again["id"] != a["id"]


async def test_declined_wave_content_is_scrubbed_after_30_days(client, session):
    owner, eid, a, b = await pair(client)
    c = await join(client, owner, eid, name="Chidi")
    await settle()
    declined = await wave(client, eid, a, b, note="Hi")
    await client.post(
        f"/v1/waves/{declined}/respond", json={"action": "not_now"}, headers=b["headers"]
    )
    kept = await wave(client, eid, a, c, note="Still open")
    clock.advance(timedelta(days=31))
    await wave_jobs.retention()
    session.expire_all()
    d, k = await session.get(Wave, declined), await session.get(Wave, kept)
    assert d is not None and d.card == {} and d.note is None
    assert k is not None and k.note == "Still open" and k.card  # pending waves are untouched


async def test_retention_crons_are_registered():
    names = {c.name for c in jobs.CRONS}
    assert {"identity.retention", "waves.retention", "chat.retention", "ai.retention"} <= names


async def test_metrics_needs_its_token(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings

    assert (await client.get("/metrics")).status_code == 404  # no token configured
    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("scrape-me"))
    assert (await client.get("/metrics")).status_code == 404
    bad = await client.get("/metrics", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 404
    await client.get("/v1/events/evt_does_not_exist")
    ok = await client.get("/metrics", headers={"Authorization": "Bearer scrape-me"})
    assert ok.status_code == 200
    # labelled by route template, so ids never become label values
    assert 'route="/events/{event_id}"' in ok.text
    assert "evt_does_not_exist" not in ok.text
