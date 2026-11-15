"""Voyage AI embeddings over HTTP (05 embedding contract: voyage-3.5, 1024 dims)."""

from typing import Literal

import httpx

from app.adapters.embeddings.port import DIMS, EmbeddingError


class VoyageEmbeddings:
    model = "voyage-3.5"

    def __init__(self, api_key: str) -> None:
        self._http = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            timeout=10,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def embed(
        self, texts: list[str], *, input_type: Literal["query", "document"]
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 128):
            try:
                r = await self._http.post(
                    "/embeddings",
                    json={
                        "input": texts[i : i + 128],
                        "model": self.model,
                        "input_type": input_type,
                        "output_dimension": DIMS,
                    },
                )
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise EmbeddingError(type(e).__name__) from e
            out.extend(d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"]))
        return out
