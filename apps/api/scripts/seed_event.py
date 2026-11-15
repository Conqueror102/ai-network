"""Seed one live event with fake attendees for local development (09 §1).

    make seed                 # 200 attendees
    make seed n=50            # fewer

It drives the real HTTP API in-process, so every row passes the same validation,
screening and outbox path as production traffic. It needs the fake OTP sender
(the dev default) and refuses to run anywhere but `ENV=dev`. Start a worker
(`make worker`) to embed the profiles and build match feeds.
"""

import asyncio
import random
import sys
from datetime import timedelta

import httpx

from app.adapters import factory
from app.bootstrap import create_app
from app.core import clock
from app.core.config import get_settings

FIRST = ["Ada", "Bayo", "Chidi", "Dami", "Efe", "Funke", "Gbenga", "Hauwa", "Ife", "Jide",
         "Kemi", "Lanre", "Mariam", "Nnamdi", "Ope", "Pelumi", "Rotimi", "Sade", "Tobi", "Uche",
         "Wale", "Yemi", "Zainab", "Amaka", "Bola"]  # fmt: skip
LAST = ["Okafor", "Adeyemi", "Bello", "Eze", "Okonkwo", "Balogun", "Ibrahim", "Nwosu",
        "Adebayo", "Olawale", "Chukwu", "Lawal", "Obi", "Salami", "Udoh"]  # fmt: skip
PERSONAS = [
    ("Fintech founder", "payments infrastructure and licensing know-how", "raise",
     "meet seed investors who back African fintech"),
    ("Angel investor", "pre-seed cheques and intros to funds", "invest",
     "find early-stage founders in fintech and logistics"),
    ("Backend engineer", "Python, Postgres and scaling APIs", "get_hired",
     "find a senior backend role at a product company"),
    ("Engineering manager", "hiring and growing engineering teams", "hire",
     "hire senior backend and mobile engineers"),
    ("Product designer", "design systems and user research", "partner",
     "partner with startups that need a design sprint"),
    ("Growth marketer", "paid acquisition and lifecycle marketing", "sell",
     "sell growth retainers to funded startups"),
    ("Logistics operator", "last-mile delivery across Lagos", "partner",
     "partner with e-commerce brands that need delivery"),
    ("Student developer", "energy, React and a lot of curiosity", "learn",
     "learn how senior engineers design systems"),
    ("Healthtech founder", "clinic networks and telemedicine", "cofounder",
     "find a technical cofounder for a healthtech startup"),
    ("Data scientist", "ML models for credit scoring", "meet",
     "meet people building with AI in finance"),
]  # fmt: skip


async def sign_in(client: httpx.AsyncClient, n: int) -> dict[str, str]:
    # the toll-fraud cap allows 30 codes an hour per number prefix, so spread them out
    phone = f"+234{7000 + n // 25:04d}{n % 25:06d}"
    ip = {"cf-connecting-ip": f"10.9.{n // 250}.{n % 250}"}
    r = await client.post(
        "/v1/auth/otp/request", json={"channel": "phone", "destination": phone}, headers=ip
    )
    r.raise_for_status()
    code = factory.otp_senders()[0].last_code(phone)  # type: ignore[attr-defined]
    r = await client.post(
        "/v1/auth/otp/verify",
        json={"request_id": r.json()["request_id"], "code": code},
        headers=ip,
    )
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def main(count: int) -> None:
    settings = get_settings()
    if settings.env != "dev":
        sys.exit("seed_event only runs with ENV=dev")
    if settings.otp_primary != "fake":
        sys.exit("seed_event needs OTP_PRIMARY=fake")
    rng = random.Random(7)
    app = create_app("api")
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://seed", timeout=30) as c,
    ):
        owner = await sign_in(c, 0)
        org = (
            await c.post("/v1/organizers", json={"name": "Seed Events Ltd"}, headers=owner)
        ).json()
        now = clock.now()
        r = await c.post(
            f"/v1/organizers/{org['id']}/events",
            json={
                "name": "DevCon Lagos (seed)",
                "venue_name": "Landmark Centre",
                "city_code": "NG-LA",
                "address": "Water Corporation Rd, Victoria Island",
                "gating": "open",
                "starts_at": (now - timedelta(hours=1)).isoformat(),
                "ends_at": (now + timedelta(hours=10)).isoformat(),
                "meeting_points": ["Coffee stand", "Main stage left", "Registration desk"],
            },
            headers=owner,
        )
        r.raise_for_status()
        eid = r.json()["id"]
        (
            await c.post(f"/v1/events/{eid}/status", json={"status": "published"}, headers=owner)
        ).raise_for_status()

        async def door_code() -> str:
            r = await c.get(f"/v1/events/{eid}/door-qr", headers=owner)
            r.raise_for_status()
            return str(r.json()["qr_token"])

        qr = await door_code()
        for n in range(1, count + 1):
            me = await sign_in(c, n)
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            headline, offer, intent, ask = rng.choice(PERSONAS)
            await c.patch("/v1/me", json={"display_name": name, "headline": headline}, headers=me)
            r = await c.post(f"/v1/events/{eid}/checkin", json={"qr_token": qr}, headers=me)
            if r.status_code != 200:  # the door code rotated: fetch the new one and retry
                qr = await door_code()
                r = await c.post(f"/v1/events/{eid}/checkin", json={"qr_token": qr}, headers=me)
            r.raise_for_status()
            (
                await c.put(
                    f"/v1/events/{eid}/profile",
                    json={"display_name": name, "headline": headline, "offer_text": offer},
                    headers=me,
                )
            ).raise_for_status()
            (
                await c.post(
                    f"/v1/events/{eid}/goals",
                    json={"priority": 1, "intent": intent, "target": {}, "raw_input": ask},
                    headers=me,
                )
            ).raise_for_status()
            if n % 25 == 0:
                print(f"  {n}/{count} attendees")
    print(f"Seeded event {eid} with {count} attendees. Organizer phone: +2347000000000")
    print("Sign in with the fake OTP code from the API log. Run `make worker` to build feeds.")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200))
