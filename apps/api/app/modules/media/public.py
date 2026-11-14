"""Media: presigned uploads to object storage. Uploads never pass through the API."""

from app.adapters import factory
from app.core.errors import ValidationFailed
from app.core.ids import new_id

ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_PHOTO_BYTES = 8 * 1024 * 1024


async def presign_photo(owner_id: str, content_type: str) -> tuple[str, str]:
    ext = ALLOWED.get(content_type)
    if ext is None:
        raise ValidationFailed("Unsupported image type", code="unsupported_media_type")
    key = f"photos/{owner_id}/{new_id('img')}.{ext}"
    url = await factory.storage().presign_put(
        key, content_type=content_type, max_bytes=MAX_PHOTO_BYTES
    )
    return url, key


def owns(owner_id: str, key: str) -> bool:
    return key.startswith(f"photos/{owner_id}/") and ".." not in key


async def exists(key: str) -> bool:
    return await factory.storage().exists(key)


def public_url(key: str) -> str:
    return factory.storage().public_url(key)
