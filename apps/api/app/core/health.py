"""Liveness and readiness (doc 11 §11)."""

import hmac

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db.engine import get_session_factory
from app.core.errors import NotFound
from app.core.observability import metrics_payload
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/livez", include_in_schema=False)
async def livez() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with get_session_factory()() as s:
            await s.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:  # noqa: BLE001 - readiness reports, never raises
        checks["db"] = "fail"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception:  # noqa: BLE001
        checks["redis"] = "fail"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        {"status": "ok" if ok else "degraded", "checks": checks}, 200 if ok else 503
    )


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus scrape target. Needs `Authorization: Bearer $METRICS_TOKEN`; without
    a configured token the route does not exist."""
    token = get_settings().metrics_token
    given = request.headers.get("authorization", "").removeprefix("Bearer ")
    if token is None or not hmac.compare_digest(given.encode(), token.get_secret_value().encode()):
        raise NotFound
    body, content_type = metrics_payload()
    return Response(body, media_type=content_type)
