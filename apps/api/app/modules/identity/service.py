"""Identity use cases: OTP sign-in, token rotation, own profile."""

import re
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import factory
from app.adapters.email.port import EmailSendError
from app.adapters.otp.port import OtpSendError
from app.core import clock, jobs, outbox, ratelimit
from app.core.auth import revoke_user
from app.core.config import get_settings
from app.core.ids import new_id
from app.core.observability import OTP_SENT
from app.core.security import turnstile
from app.core.security.hashing import constant_time_eq, hmac_hash, otp_code, random_token
from app.core.security.jwt import issue_access_token
from app.modules.ai import public as ai
from app.modules.identity import errors
from app.modules.identity.models import AuthOtp, PushSubscription, RefreshToken, User
from app.modules.identity.schemas import MePatchIn, UserOut
from app.modules.media import public as media

log = structlog.get_logger()
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
RESEND_AFTER_S = 60
SCREENED_FIELDS = ("display_name", "headline", "bio", "role_title", "company")


def normalize_destination(channel: str, destination: str) -> str:
    if channel == "phone":
        phone = re.sub(r"[\s()-]", "", destination)
        allow = get_settings().otp_sms_country_allowlist
        if not _E164.match(phone) or not any(phone.startswith(p) for p in allow):
            raise errors.InvalidDestination
        return phone
    email = destination.strip().lower()
    if not _EMAIL.match(email):
        raise errors.InvalidDestination
    return email


def is_premium(user: User) -> bool:
    return user.premium_until is not None and user.premium_until > clock.now()


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        phone=user.phone,
        email=user.email,
        real_name=user.real_name,
        display_name=user.display_name,
        photo_url=media.public_url(user.photo_key)
        if user.photo_key and user.photo_status == "approved"
        else None,
        photo_status=user.photo_status,
        headline=user.headline,
        bio=user.bio,
        role_title=user.role_title,
        company=user.company,
        industry=user.industry,
        skills=user.skills,
        links=user.links,
        share_email=user.share_email,
        share_phone=user.share_phone,
        premium=is_premium(user),
        created_at=user.created_at,
    )


# --- OTP -------------------------------------------------------------------------------


async def request_otp(
    session: AsyncSession, *, channel: str, destination: str, turnstile_token: str | None, ip: str
) -> str:
    dest = normalize_destination(channel, destination)
    if not await turnstile.verify(turnstile_token, ip):
        raise errors.ChallengeFailed
    # 08 §6 toll-fraud caps. OTP sending fails closed when Redis is down.
    limits = [
        ("otp_dest_10m", dest, 3, 600),
        ("otp_dest_day", dest, 10, 86400),
        ("otp_ip_hour", ip, 10, 3600),
    ]
    if channel == "phone":
        limits.append(("otp_prefix_hour", dest[:8], 30, 3600))
    await ratelimit.hit(
        "otp_resend",
        dest,
        limit=1,
        window_s=RESEND_AFTER_S,
        code="otp_rate_limited",
        fail_open=False,
    )
    for scope, ident, limit, window in limits:
        await ratelimit.hit(
            scope, ident, limit=limit, window_s=window, code="otp_rate_limited", fail_open=False
        )

    code = otp_code()
    otp_id = new_id("otp")
    session.add(
        AuthOtp(
            id=otp_id,
            channel=channel,
            destination=dest,
            code_hash=hmac_hash(f"{otp_id}:{code}"),
            expires_at=clock.now() + timedelta(seconds=get_settings().otp_ttl_s),
        )
    )
    await _deliver(channel, dest, code)
    await session.commit()
    return otp_id


async def _deliver(channel: str, dest: str, code: str) -> None:
    if channel == "email":
        try:
            await factory.email().send(
                to=dest,
                subject="Your AiNetwork code",
                html=f"<p>Your AiNetwork code is <b>{code}</b>. It expires in 10 minutes.</p>",
            )
        except EmailSendError as e:
            OTP_SENT.labels("email", "error").inc()
            raise errors.OtpUndeliverable from e
        OTP_SENT.labels("email", "ok").inc()
        return
    for sender in factory.otp_senders():  # primary, then fallback
        try:
            await sender.send(channel="phone", destination=dest, code=code)
        except OtpSendError:
            OTP_SENT.labels(sender.name, "error").inc()
            log.warning("otp_send_failed", provider=sender.name)
            continue
        OTP_SENT.labels(sender.name, "ok").inc()
        return
    raise errors.OtpUndeliverable


async def verify_otp(
    session: AsyncSession, *, request_id: str, code: str, device_info: dict[str, Any] | None
) -> tuple[User, bool, str, str]:
    otp = (
        await session.execute(select(AuthOtp).where(AuthOtp.id == request_id).with_for_update())
    ).scalar_one_or_none()
    if otp is None or otp.consumed_at is not None:
        raise errors.OtpInvalid
    if otp.expires_at < clock.now():
        raise errors.OtpExpired
    if otp.attempts >= get_settings().otp_max_attempts:
        raise errors.OtpAttemptsExceeded
    if not constant_time_eq(otp.code_hash, hmac_hash(f"{otp.id}:{code}")):
        otp.attempts += 1
        await session.commit()  # the failed attempt must be recorded
        raise errors.OtpInvalid
    otp.consumed_at = clock.now()

    column = User.phone if otp.channel == "phone" else User.email
    user = (
        await session.execute(
            select(User).where(column == otp.destination, User.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    is_new = user is None
    if user is None:
        user = User(
            id=new_id("usr"),
            verified_at=clock.now(),
            skills=[],
            links=[],
            photo_status="none",
            **{column.key: otp.destination},
        )
        session.add(user)
        await session.flush()
        outbox.emit(session, "identity.user_created", {"user_id": user.id})
    if user.suspended_at is not None:
        raise errors.OtpInvalid
    access, refresh = await _issue_tokens(
        session, user, family_id=new_id("fam"), device_info=device_info
    )
    await session.commit()
    return user, is_new, access, refresh


# --- tokens ----------------------------------------------------------------------------


async def _issue_tokens(
    session: AsyncSession, user: User, *, family_id: str, device_info: dict[str, Any] | None
) -> tuple[str, str]:
    raw = f"rt_{random_token(32)}"
    session.add(
        RefreshToken(
            id=new_id("tok"),
            user_id=user.id,
            family_id=family_id,
            token_hash=hmac_hash(raw),
            device_info=device_info,
            expires_at=clock.now() + timedelta(seconds=get_settings().refresh_ttl_s),
        )
    )
    return issue_access_token(user.id, premium=is_premium(user), staff=user.is_staff), raw


async def refresh(session: AsyncSession, raw: str) -> tuple[str, str]:
    token = (
        await session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == hmac_hash(raw)).with_for_update()
        )
    ).scalar_one_or_none()
    if token is None or token.expires_at < clock.now():
        raise errors.RefreshInvalid
    if token.revoked_at is not None:
        # a rotated token was presented again: assume theft, revoke the whole family
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == token.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=clock.now())
        )
        await session.commit()
        log.warning("refresh_token_reuse", user_id=token.user_id, family_id=token.family_id)
        raise errors.RefreshReused
    user = await session.get(User, token.user_id)
    if user is None or user.deleted_at is not None or user.suspended_at is not None:
        raise errors.RefreshInvalid
    token.revoked_at = clock.now()
    tokens = await _issue_tokens(
        session, user, family_id=token.family_id, device_info=token.device_info
    )
    await session.commit()
    return tokens


async def logout(session: AsyncSession, user_id: str, raw: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hmac_hash(raw), RefreshToken.user_id == user_id)
        .values(revoked_at=clock.now())
    )
    await session.commit()


async def logout_everywhere(session: AsyncSession, user_id: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )
    await session.commit()
    await revoke_user(user_id)


# --- profile ---------------------------------------------------------------------------


async def get_active_user(session: AsyncSession, user_id: str) -> User:
    user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None or user.suspended_at is not None:
        from app.core.errors import Unauthenticated

        raise Unauthenticated
    return user


async def update_me(session: AsyncSession, user_id: str, patch: MePatchIn) -> User:
    user = await get_active_user(session, user_id)
    data = patch.model_dump(exclude_unset=True, mode="json")
    text = " \n ".join(str(data[f]) for f in SCREENED_FIELDS if data.get(f))
    rescreen = False
    if text:
        try:
            verdict = await ai.screen(text, kind="profile", user_id=user_id)
        except ai.AiUnavailable:
            rescreen = True  # accept now, screen as soon as AI is back
        else:
            if not verdict.allow:
                raise errors.ContentRejected(details={"category": verdict.category})
    for field, value in data.items():
        setattr(user, field, value)
    outbox.emit(session, "identity.profile_updated", {"user_id": user.id})
    await session.commit()
    if rescreen:
        await jobs.enqueue(
            "identity.rescreen_profile", user.id, job_id=f"rescreen:{user.id}", defer_s=120
        )
    return user


async def presign_photo(user_id: str, content_type: str) -> tuple[str, str]:
    return await media.presign_photo(user_id, content_type)


async def commit_photo(session: AsyncSession, user_id: str, key: str) -> User:
    user = await get_active_user(session, user_id)
    if not media.owns(user_id, key) or not await media.exists(key):
        raise errors.PhotoNotUploaded
    user.photo_key = key
    user.photo_status = "pending"
    await session.commit()
    await jobs.enqueue("identity.moderate_photo", user.id, key)
    return user


async def upsert_push_subscription(
    session: AsyncSession,
    user_id: str,
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: str | None,
) -> None:
    sub = (
        await session.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    ).scalar_one_or_none()
    if sub is None:
        session.add(
            PushSubscription(
                id=new_id("psh"),
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                last_seen_at=clock.now(),
            )
        )
    else:
        sub.user_id, sub.p256dh, sub.auth = user_id, p256dh, auth
        sub.last_seen_at = clock.now()
    await session.commit()


async def soft_delete(session: AsyncSession, user_id: str) -> None:
    """Soft delete now; PII is hard-deleted 30 days later by the retention job (02)."""
    user = await get_active_user(session, user_id)
    user.deleted_at = clock.now()
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=clock.now())
    )
    outbox.emit(session, "identity.user_deleted", {"user_id": user_id})
    await session.commit()
    await revoke_user(user_id)
