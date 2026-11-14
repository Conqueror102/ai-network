"""08 §6: organizer A can never read or change organizer B's events, attendees or stats."""

import pytest

from tests.helpers import make_event, sign_up

ORG_ROUTES = [
    ("GET", "/v1/events/{e}/stats/live", None),
    ("GET", "/v1/events/{e}/door-qr", None),
    ("GET", "/v1/events/{e}/applications", None),
    ("PATCH", "/v1/events/{e}", {"name": "Hijacked"}),
    ("POST", "/v1/events/{e}/status", {"status": "cancelled"}),
    ("POST", "/v1/events/{e}/announcements", {"body": "spam"}),
    ("GET", "/v1/organizers/{o}/events", None),
    (
        "POST",
        "/v1/organizers/{o}/events",
        {
            "name": "Evil",
            "venue_name": "v",
            "city_code": "NG-LA",
            "starts_at": "2030-01-01T10:00:00Z",
            "ends_at": "2030-01-01T18:00:00Z",
        },
    ),
    ("GET", "/v1/organizers/{o}/members", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ORG_ROUTES)
async def test_other_organizer_gets_404(client, method, path, body):
    owner_a, owner_b = await sign_up(client), await sign_up(client)
    event_a = await make_event(client, owner_a)
    await make_event(client, owner_b)
    url = path.format(e=event_a["id"], o=owner_a["org_id"])
    r = await client.request(method, url, json=body, headers=owner_b["headers"])
    assert r.status_code == 404, f"{method} {url} leaked to another tenant: {r.status_code}"
    anon = await client.request(method, url, json=body)
    assert anon.status_code == 401
