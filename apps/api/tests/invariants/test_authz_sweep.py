"""Authorization sweep (08 §4, doc 11 §8): every route is closed by default.

The route list comes from the running app, so a new endpoint is covered the day it
is added. A route that should be public has to be added to PUBLIC on purpose.
Payment webhooks are not in the OpenAPI schema; their signature check is covered in
tests/integration/test_billing.py.
"""

from tests.helpers import sign_up

# Reachable without a token, each for a stated reason.
PUBLIC = {
    ("GET", "/v1/events"),  # public discovery: published events, no address, IP limited
    ("POST", "/v1/auth/otp/request"),  # sign-in starts here; rate limited per IP
    ("POST", "/v1/auth/otp/verify"),
    ("POST", "/v1/auth/refresh"),  # authenticated by the refresh token itself
    ("POST", "/v1/auth/logout"),  # same
}


def api_routes(app):
    methods = {"get", "post", "put", "patch", "delete"}
    for path, item in sorted(app.openapi()["paths"].items()):
        if path.startswith("/v1/"):
            for method in sorted(methods & set(item)):
                yield method.upper(), path


def fill(path: str) -> str:
    out = []
    for part in path.split("/"):
        out.append("zz_missing" if part.startswith("{") else part)
    return "/".join(out)


async def test_every_route_requires_a_token(client, app):
    seen = set()
    for method, path in api_routes(app):
        seen.add((method, path))
        if (method, path) in PUBLIC:
            continue
        r = await client.request(method, fill(path), json={})
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"
    assert len(seen) > 80  # the sweep really walked the app
    assert seen >= PUBLIC, f"stale PUBLIC entries: {PUBLIC - seen}"


async def test_garbage_tokens_are_refused(client, app):
    for method, path in api_routes(app):
        if (method, path) in PUBLIC:
            continue
        r = await client.request(
            method, fill(path), json={}, headers={"Authorization": "Bearer not.a.token"}
        )
        assert r.status_code == 401, f"{method} {path} accepted a garbage token"


async def test_internal_routes_do_not_exist_for_non_staff(client, app):
    user = await sign_up(client)
    internal = [(m, p) for m, p in api_routes(app) if p.startswith("/v1/internal/")]
    assert len(internal) >= 10
    for method, path in internal:
        r = await client.request(method, fill(path), json={}, headers=user["headers"])
        assert r.status_code == 404, f"{method} {path} is visible to non-staff: {r.status_code}"


async def test_unknown_ids_never_answer_403(client, app):
    """Forbidden and missing look the same (404), so ids cannot be probed (08 §4)."""
    user = await sign_up(client)
    for method, path in api_routes(app):
        if "{" not in path or (method, path) in PUBLIC:
            continue
        r = await client.request(method, fill(path), json={}, headers=user["headers"])
        assert r.status_code != 403, f"{method} {path} answered 403 for an unknown id"
        assert r.status_code < 500, f"{method} {path} crashed: {r.status_code}"
