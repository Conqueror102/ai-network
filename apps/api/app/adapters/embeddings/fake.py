"""Deterministic hashed bag-of-words embeddings: overlapping words => similar vectors."""

import hashlib
import math
import re
from typing import Literal

from app.adapters.embeddings.port import DIMS, EmbeddingError

_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "i",
    "we",
    "is",
    "are",
    "who",
    "with",
    "looking",
    "profile",
    "roles",
    "industries",
    "stage",
    "my",
}


class FakeEmbeddings:
    model = "fake-bow-v1"
    fail = False  # tests flip this to simulate a provider outage

    async def embed(
        self, texts: list[str], *, input_type: Literal["query", "document"]
    ) -> list[list[float]]:
        if self.fail:
            raise EmbeddingError("fake outage")
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        vec = [0.0] * DIMS
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            if word in _STOP:
                continue
            word = word.rstrip("s")
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "big")
            vec[h % DIMS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]
