"""Authentication dependencies. Authorization lives in module policies/deps."""

from dataclasses import dataclass
from typing import Annotated

import structlog
from fastapi import Depends, Request
from redis.exceptions import RedisError

from app.core import ratelimit
from app.core.config import get_settings
from app.core.errors import NotFound, Unauthenticated
from app.core.redis import get_redis, key
from app.core.security.jwt import verify_access_token


@dataclass(frozen=True)
class Principal:
    user_id: str
    premium: bool = False
    staff: bool = False


async def current_principal(request: Request) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise Unauthenticated
    claims = verify_access_token(token)
    principal = Principal(claims["sub"], bool(claims.get("premium")), bool(claims.get("staff")))
    if await is_revoked(principal.user_id):
        raise Unauthenticated("Session revoked", code="token_revoked")
    structlog.contextvars.bind_contextvars(user_id=principal.user_id)
    # global default: 120 req/min per user (03 §12)
    await ratelimit.hit("global", principal.user_id, limit=120, window_s=60)
    return principal


async def revoke_user(user_id: str) -> None:
    """Deny this user's outstanding access tokens until they would have expired."""
    await get_redis().set(
        key("cache", "revoked", user_id), "1", ex=get_settings().access_ttl_s + 30
    )


async def is_revoked(user_id: str) -> bool:
    try:
        return bool(await get_redis().exists(key("cache", "revoked", user_id)))
    except RedisError:
        return False


CurrentUser = Annotated[Principal, Depends(current_principal)]


async def require_staff(request: Request, principal: CurrentUser) -> Principal:
    """Internal/admin routes: staff claim + IP allowlist. 404 hides their existence."""
    allow = get_settings().staff_ip_allowlist
    if not principal.staff or (allow and ratelimit.client_ip(request) not in allow):
        raise NotFound
    return principal


StaffUser = Annotated[Principal, Depends(require_staff)]
