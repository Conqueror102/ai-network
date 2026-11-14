from fastapi import APIRouter, Request, Response

from app.core import ratelimit
from app.core.auth import CurrentUser
from app.core.db.engine import DbSession
from app.modules.identity import schemas, service
from app.modules.media.public import MAX_PHOTO_BYTES

router = APIRouter(tags=["identity"])


@router.post("/auth/otp/request", response_model=schemas.OtpRequestOut)
async def otp_request(
    body: schemas.OtpRequestIn, request: Request, session: DbSession
) -> schemas.OtpRequestOut:
    ip = ratelimit.client_ip(request)
    await ratelimit.hit("ip_unauth", ip, limit=20, window_s=60)
    request_id = await service.request_otp(
        session,
        channel=body.channel,
        destination=body.destination,
        turnstile_token=body.turnstile_token,
        ip=ip,
    )
    return schemas.OtpRequestOut(request_id=request_id, resend_after_s=service.RESEND_AFTER_S)


@router.post("/auth/otp/verify", response_model=schemas.VerifyOut)
async def otp_verify(
    body: schemas.OtpVerifyIn, request: Request, session: DbSession
) -> schemas.VerifyOut:
    await ratelimit.hit("ip_unauth", ratelimit.client_ip(request), limit=20, window_s=60)
    user, is_new, access, refresh = await service.verify_otp(
        session,
        request_id=body.request_id,
        code=body.code,
        device_info={"user_agent": request.headers.get("user-agent", "")[:200]},
    )
    return schemas.VerifyOut(
        access_token=access, refresh_token=refresh, user=service.to_user_out(user), is_new=is_new
    )


@router.post("/auth/refresh", response_model=schemas.TokensOut)
async def refresh(
    body: schemas.RefreshIn, request: Request, session: DbSession
) -> schemas.TokensOut:
    await ratelimit.hit("ip_unauth", ratelimit.client_ip(request), limit=20, window_s=60)
    access, new_refresh = await service.refresh(session, body.refresh_token)
    return schemas.TokensOut(access_token=access, refresh_token=new_refresh)


@router.post("/auth/logout", status_code=204)
async def logout(body: schemas.RefreshIn, user: CurrentUser, session: DbSession) -> Response:
    await service.logout(session, user.user_id, body.refresh_token)
    return Response(status_code=204)


@router.post("/auth/logout-all", status_code=204)
async def logout_all(user: CurrentUser, session: DbSession) -> Response:
    await service.logout_everywhere(session, user.user_id)
    return Response(status_code=204)


@router.get("/me", response_model=schemas.UserOut)
async def get_me(user: CurrentUser, session: DbSession) -> schemas.UserOut:
    return service.to_user_out(await service.get_active_user(session, user.user_id))


@router.patch("/me", response_model=schemas.UserOut)
async def patch_me(
    body: schemas.MePatchIn, user: CurrentUser, session: DbSession
) -> schemas.UserOut:
    return service.to_user_out(await service.update_me(session, user.user_id, body))


@router.delete("/me", status_code=204)
async def delete_me(user: CurrentUser, session: DbSession) -> Response:
    await service.soft_delete(session, user.user_id)
    return Response(status_code=204)


@router.post("/me/photo/presign", response_model=schemas.PhotoPresignOut)
async def photo_presign(body: schemas.PhotoPresignIn, user: CurrentUser) -> schemas.PhotoPresignOut:
    url, key = await service.presign_photo(user.user_id, body.content_type)
    return schemas.PhotoPresignOut(upload_url=url, key=key, max_bytes=MAX_PHOTO_BYTES)


@router.post("/me/photo/commit", response_model=schemas.UserOut)
async def photo_commit(
    body: schemas.PhotoCommitIn, user: CurrentUser, session: DbSession
) -> schemas.UserOut:
    return service.to_user_out(await service.commit_photo(session, user.user_id, body.key))


@router.post("/me/push-subscriptions", status_code=204)
async def push_subscribe(
    body: schemas.PushSubscriptionIn, request: Request, user: CurrentUser, session: DbSession
) -> Response:
    await service.upsert_push_subscription(
        session,
        user.user_id,
        endpoint=str(body.endpoint),
        p256dh=body.p256dh,
        auth=body.auth,
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    return Response(status_code=204)
