from sqlalchemy import select

from app.core.security.jwt import issue_access_token
from app.modules.safety.models import Report
from tests.helpers import join, make_event, sign_up


async def test_report_and_moderation_queue(client, session):
    owner = await sign_up(client)
    eid = (await make_event(client, owner))["id"]
    a = await join(client, owner, eid, name="Ada")
    b = await join(client, owner, eid, name="Bayo")
    staff = {"Authorization": f"Bearer {issue_access_token(owner['id'], staff=True)}"}

    r = await client.post(
        "/v1/reports",
        json={"subject_id": b["id"], "reason": "spam", "detail": "ads", "event_id": eid},
        headers=a["headers"],
    )
    assert r.status_code == 204
    r = await client.post(
        "/v1/reports", json={"subject_id": a["id"], "reason": "spam"}, headers=a["headers"]
    )
    assert r.status_code == 422
    r = await client.post(
        "/v1/reports", json={"subject_id": b["id"], "reason": "rude"}, headers=a["headers"]
    )
    assert r.status_code == 422

    # the queue is invisible to non-staff
    assert (
        await client.get("/v1/internal/moderation/reports", headers=a["headers"])
    ).status_code == 404
    queue = (await client.get("/v1/internal/moderation/reports", headers=staff)).json()["items"]
    assert len(queue) == 1 and queue[0]["reason"] == "spam"
    rid = queue[0]["id"]

    # suspend from this event only: the event room closes, the account lives on
    r = await client.post(
        f"/v1/internal/moderation/reports/{rid}/action",
        json={"action": "suspend_event"},
        headers=staff,
    )
    assert r.json()["status"] == "actioned"
    r = await client.get(f"/v1/events/{eid}/room", headers=b["headers"])
    assert r.json()["error"]["code"] == "event_access_suspended"
    assert (await client.get("/v1/me", headers=b["headers"])).status_code == 200
    r = await client.post(
        f"/v1/internal/moderation/reports/{rid}/action", json={"action": "ban"}, headers=staff
    )
    assert r.json()["error"]["code"] == "report_closed"

    # ban: every token of the account stops working at once
    await client.post(
        "/v1/reports", json={"subject_id": b["id"], "reason": "harassment"}, headers=a["headers"]
    )
    rid2 = (await client.get("/v1/internal/moderation/reports", headers=staff)).json()["items"][0][
        "id"
    ]
    await client.post(
        f"/v1/internal/moderation/reports/{rid2}/action", json={"action": "ban"}, headers=staff
    )
    assert (await client.get("/v1/me", headers=b["headers"])).status_code == 401
    flags = (await client.get("/v1/internal/moderation/flags", headers=staff)).json()
    assert [f["kind"] for f in flags] == ["event_suspended"]
    r = await client.post(f"/v1/internal/moderation/flags/{flags[0]['id']}/resolve", headers=staff)
    assert r.status_code == 204
    assert len((await session.execute(select(Report))).all()) == 2
