"""Cloudflare R2 (S3-compatible). boto3 is sync, so calls run in a thread."""

import asyncio
from typing import Any

import boto3
from botocore.exceptions import ClientError


class R2Storage:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        cdn_base_url: str,
    ) -> None:
        self._bucket, self._cdn = bucket, cdn_base_url.rstrip("/")
        self._s3: Any = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    async def presign_put(
        self, key: str, *, content_type: str, max_bytes: int, expires_s: int = 300
    ) -> str:
        # content type is pinned in the signature; size is re-checked on commit
        return await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_s,
        )

    async def exists(self, key: str) -> bool:
        try:
            await asyncio.to_thread(self._s3.head_object, Bucket=self._bucket, Key=key)
        except ClientError:
            return False
        return True

    async def size(self, key: str) -> int:
        head = await asyncio.to_thread(self._s3.head_object, Bucket=self._bucket, Key=key)
        return int(head["ContentLength"])

    def public_url(self, key: str) -> str:
        return f"{self._cdn}/{key}"

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._s3.delete_object, Bucket=self._bucket, Key=key)
