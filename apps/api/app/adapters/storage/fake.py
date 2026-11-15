class FakeStorage:
    def __init__(self) -> None:
        self.objects: set[str] = set()

    async def presign_put(
        self, key: str, *, content_type: str, max_bytes: int, expires_s: int = 300
    ) -> str:
        return f"https://fake-storage.local/upload/{key}?ct={content_type}"

    async def exists(self, key: str) -> bool:
        return key in self.objects

    def public_url(self, key: str) -> str:
        return f"https://fake-cdn.local/{key}"

    async def delete(self, key: str) -> None:
        self.objects.discard(key)
