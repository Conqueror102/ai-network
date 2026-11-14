"""Shared test helpers: sign users in through the real OTP flow."""

import itertools

from app.adapters import factory

_counter = itertools.count(1)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_up(client, *, name: str | None = None, phone: str | None = None) -> dict:
    """Returns {"id", "token", "refresh", "headers", "phone"}."""
    n = next(_counter)
    phone = phone or f"+23480{n:08d}"
    r = await client.post(
        "/v1/auth/otp/request",
        json={"channel": "phone", "destination": phone},
        headers={"cf-connecting-ip": f"10.0.{n // 250}.{n % 250}"},
    )
    assert r.status_code == 200, r.text
    code = factory.otp_senders()[0].last_code(phone)
    r = await client.post(
        "/v1/auth/otp/verify", json={"request_id": r.json()["request_id"], "code": code}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    user = {
        "id": body["user"]["id"],
        "token": body["access_token"],
        "refresh": body["refresh_token"],
        "headers": auth(body["access_token"]),
        "phone": phone,
    }
    if name:
        r = await client.patch("/v1/me", json={"display_name": name}, headers=user["headers"])
        assert r.status_code == 200, r.text
    return user


from datetime import timedelta  # noqa: E402

from app.core import clock  # noqa: E402


async def make_event(
    client,
    owner: dict,
    *,
    gating: str = "open",
    publish: bool = True,
    capacity: int | None = None,
    name: str = "DevCon Lagos",
) -> dict:
    """Creates an organizer (if needed) and a published event that is live now."""
    if "org_id" not in owner:
        r = await client.post(
            "/v1/organizers", json={"name": f"Org of {owner['id'][-6:]}"}, headers=owner["headers"]
        )
        assert r.status_code == 201, r.text
        owner["org_id"] = r.json()["id"]
    now = clock.now()
    body = {
        "name": name,
        "venue_name": "Landmark Centre",
        "city_code": "NG-LA",
        "address": "Water Corporation Rd",
        "gating": gating,
        "starts_at": (now - timedelta(minutes=30)).isoformat(),
        "ends_at": (now + timedelta(hours=8)).isoformat(),
        "meeting_points": ["Coffee stand", "Main stage left"],
    }
    if capacity:
        body["capacity"] = capacity
    r = await client.post(
        f"/v1/organizers/{owner['org_id']}/events", json=body, headers=owner["headers"]
    )
    assert r.status_code == 201, r.text
    event = r.json()
    if publish:
        r = await client.post(
            f"/v1/events/{event['id']}/status",
            json={"status": "published"},
            headers=owner["headers"],
        )
        assert r.status_code == 200, r.text
    return event


async def check_in(client, owner: dict, event_id: str, user: dict) -> None:
    token = (await client.get(f"/v1/events/{event_id}/door-qr", headers=owner["headers"])).json()[
        "qr_token"
    ]
    r = await client.post(
        f"/v1/events/{event_id}/checkin", json={"qr_token": token}, headers=user["headers"]
    )
    assert r.status_code == 200, r.text
