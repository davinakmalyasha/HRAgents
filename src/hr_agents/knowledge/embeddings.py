"""Embedding providers.

The default provider is deterministic and fully offline so the system runs (and
tests) without any API keys. API-backed providers plug into the same protocol in
the integrations phase; the retriever never depends on which one is active.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
        "dan",
        "atau",
        "yang",
        "untuk",
        "dengan",
        "di",
        "ke",
        "dari",
        "ini",
        "itu",
    }
)


def tokenize(text: str) -> list[str]:
    """Lowercase tokenization shared by embeddings and keyword scoring."""
    return _TOKEN_RE.findall(text.lower())


def meaningful_tokens(text: str) -> list[str]:
    """Tokens with common English/Indonesian stopwords removed."""
    return [token for token in tokenize(text) if token not in _STOPWORDS and len(token) > 1]


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for embedding backends."""

    @property
    def model_name(self) -> str: ...

    @property
    def dimension(self) -> int: ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity between two vectors (0.0 when either is empty)."""
    if len(left) != len(right):
        raise ValueError("vectors must have the same dimension")
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))


class HashEmbeddingProvider:
    """Deterministic, offline signed-hashing bag-of-words embeddings.

    Stable across processes, machines, and Python versions (uses BLAKE2b, not
    the salted builtin ``hash``). Intended for offline mode, tests, and
    development — semantic quality is intentionally modest; swap in an
    API-backed provider for production semantic recall.
    """

    def __init__(self, dimension: int = 256) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def model_name(self) -> str:
        return f"hash-bow-v1-{self._dimension}"

    @property
    def dimension(self) -> int:
        return self._dimension

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimension
        tokens = meaningful_tokens(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=9).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimension
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm > 0.0:
            vector = [value / norm for value in vector]
        return vector

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]
