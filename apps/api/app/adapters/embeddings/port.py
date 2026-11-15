from typing import Literal, Protocol

DIMS = 1024


class EmbeddingError(Exception):
    pass


class EmbeddingProvider(Protocol):
    model: str

    async def embed(
        self, texts: list[str], *, input_type: Literal["query", "document"]
    ) -> list[list[float]]: ...
