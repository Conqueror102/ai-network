from datetime import timedelta

import pytest
from fastapi import APIRouter

from app.core import clock, flags, idempotency, jobs, outbox, ratelimit
from app.core.db.pagination import decode_cursor, encode_cursor, paginate
from app.core.errors import Conflict, RateLimited, ValidationFailed
from app.core.ids import new_id
from app.core.logging import scrub
from app.core.security import crypto
from app.core.security.jwt import issue_access_token, verify_access_token


async def test_health(client):
    assert (await client.get("/livez")).json() == {"status": "ok"}
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"] == {"db": "ok", "redis": "ok"}


async def test_error_envelope_and_headers(client):
    r = await client.get("/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert r.headers["x-request-id"].startswith("req_")
    assert r.headers["x-content-type-options"] == "nosniff"


async def test_unhandled_error_hides_details(app, client):
    router = APIRouter()

    @router.get("/boom")
    async def boom():
        raise RuntimeError("secret sql details")

    app.include_router(router)
    r = await client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret" not in r.text


async def test_body_size_limit(client):
    r = await client.post("/v1/nope", content=b"x" * 1_100_000)
    assert r.status_code == 413


def test_ids_are_prefixed_and_sortable():
    a, b = new_id("usr"), new_id("usr")
    assert a.startswith("usr_") and len(a) == 30 and a != b


def test_cursor_roundtrip():
    assert decode_cursor(encode_cursor(["x", 1])) == ["x", 1]
    with pytest.raises(ValidationFailed):
        decode_cursor("!!!")
    rows, nxt = paginate([1, 2, 3], 2, lambda r: r)
    assert rows == [1, 2] and decode_cursor(nxt) == 2


def test_crypto_roundtrip():
    token = crypto.encrypt("hello")
    assert "hello" not in token and crypto.decrypt(token) == "hello"


def test_log_scrubber():
    out = scrub({"msg": "call +2348012345678 or a@b.co", "code": "123456"})
    assert out == {"msg": "call [phone] or [email]", "code": "[redacted]"}


def test_jwt_roundtrip_and_expiry():
    from app.core.errors import Unauthenticated

    tok = issue_access_token("usr_1")
    assert verify_access_token(tok)["sub"] == "usr_1"
    clock.advance(timedelta(days=41))
    with pytest.raises(Unauthenticated):
        verify_access_token(tok)
    with pytest.raises(Unauthenticated):
        verify_access_token(tok[:-2] + "xx")


async def test_rate_limit():
    for _ in range(3):
        await ratelimit.hit("t", "u1", limit=3, window_s=60)
    with pytest.raises(RateLimited) as e:
        await ratelimit.hit("t", "u1", limit=3, window_s=60)
    assert e.value.details["retry_after_s"] >= 1
    await ratelimit.hit("t", "u2", limit=3, window_s=60)


async def test_idempotency():
    assert await idempotency.lookup("u", "k1", {"a": 1}) is None
    await idempotency.store("u", "k1", {"a": 1}, {"id": "x"})
    assert await idempotency.lookup("u", "k1", {"a": 1}) == {"id": "x"}
    with pytest.raises(Conflict):
        await idempotency.lookup("u", "k1", {"a": 2})


async def test_flags():
    assert await flags.is_enabled("ai.wingman") is True
    await flags.set_flag("ai.wingman", False)
    assert await flags.is_enabled("ai.wingman") is False


async def test_outbox_delivers_once_and_retries(session):
    seen: list[str] = []
    fail = {"n": 2}

    @outbox.subscribe("test.topic")
    async def handler(payload):
        if fail["n"] > 0:
            fail["n"] -= 1
            raise RuntimeError("transient")
        seen.append(payload["x"])

    outbox.emit(session, "test.topic", {"x": "1"})
    await session.commit()
    assert await outbox.relay_once() == 0  # first attempt fails
    clock.advance(timedelta(minutes=1))
    assert await outbox.relay_once() == 0  # second attempt fails
    clock.advance(timedelta(minutes=1))
    assert await outbox.relay_once() == 1
    assert await outbox.relay_once() == 0  # never redelivered once processed
    assert seen == ["1"]


async def test_outbox_rolls_back_with_transaction(session):
    outbox.emit(session, "test.rollback", {"x": "1"})
    await session.rollback()
    assert await outbox.relay_once() == 0


async def test_jobs_dedupe_and_run():
    ran = []

    @jobs.job("test.job")
    async def j(x):
        ran.append(x)

    await jobs.enqueue("test.job", 1, job_id="a")
    await jobs.enqueue("test.job", 1, job_id="a")
    await jobs.enqueue("test.job", 2)
    assert await jobs.run_pending() == 2 and ran == [1, 2]
