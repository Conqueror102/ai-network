"""Access JWTs: HS256 with kid rotation (08 §1)."""

from typing import Any

import jwt

from app.core import clock
from app.core.config import get_settings
from app.core.errors import Unauthenticated
from app.core.ids import new_id


def _secrets() -> dict[str, str]:
    s = get_settings()
    out = {s.jwt_kid: s.jwt_secret.get_secret_value()}
    if s.jwt_secret_next is not None:
        out[s.jwt_kid_next] = s.jwt_secret_next.get_secret_value()
    return out


def issue_access_token(user_id: str, *, premium: bool = False, staff: bool = False) -> str:
    s = get_settings()
    iat = int(clock.now().timestamp())
    claims = {
        "sub": user_id,
        "iat": iat,
        "exp": iat + s.access_ttl_s,
        "jti": new_id("jti"),
        "premium": premium,
        "staff": staff,
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
    }
    return jwt.encode(
        claims, s.jwt_secret.get_secret_value(), algorithm="HS256", headers={"kid": s.jwt_kid}
    )


def verify_access_token(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        secret = _secrets().get(kid or "")
        if secret is None:
            raise Unauthenticated("Invalid token", code="token_invalid")
        claims: dict[str, Any] = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=s.jwt_audience,
            issuer=s.jwt_issuer,
            leeway=10,
            options={"require": ["sub", "exp", "iat", "jti"], "verify_exp": False},
        )
    except jwt.PyJWTError as e:
        raise Unauthenticated("Invalid token", code="token_invalid") from e
    # expiry checked against the injectable clock so tests can time-warp
    if claims["exp"] + 10 < clock.now().timestamp():
        raise Unauthenticated("Token expired", code="token_expired")
    return claims
