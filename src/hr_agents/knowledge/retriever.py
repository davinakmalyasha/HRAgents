"""Namespace-scoped hybrid retriever.

Scoring combines embedding similarity with keyword overlap so exact terms
(e.g., "BPJS", "PKWT", "Docker") surface even with modest embeddings. Every hit
carries a full citation; namespace access is enforced per call — an agent can
never retrieve outside its permitted scopes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pydantic import Field

from hr_agents.knowledge.chunking import KnowledgeChunk, chunk_documents
from hr_agents.knowledge.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    cosine_similarity,
    meaningful_tokens,
)
from hr_agents.models import StrictModel
from hr_agents.skills.models import KnowledgeDoc

DEFAULT_VECTOR_WEIGHT = 0.6
DEFAULT_KEYWORD_WEIGHT = 0.4
DEFAULT_LIMIT = 5


class NamespaceAccessError(PermissionError):
    """Raised when a caller requests a namespace it is not permitted to use."""


class RetrievalHit(StrictModel):
    """A scored retrieval result with citation metadata."""

    chunk_id: str
    doc_id: str
    title: str
    namespace: str
    heading_path: list[str] = Field(default_factory=list)
    text: str
    score: float = Field(ge=0.0)
    vector_score: float = Field(ge=0.0)
    keyword_score: float = Field(ge=0.0)

    def citation(self) -> str:
        breadcrumb = " > ".join(self.heading_path) if self.heading_path else self.title
        return f"{self.title} — {breadcrumb} ({self.doc_id})"


def _namespace_allows(requested: str, available: str) -> bool:
    return available == requested or available.startswith(requested + ".")


class KnowledgeRetriever:
    """In-memory hybrid retriever.

    The index is built once from chunked knowledge documents. A PostgreSQL +
    pgvector adapter implements the same query surface in the integrations
    phase; callers never notice the difference.
    """

    def __init__(
        self,
        chunks: Sequence[KnowledgeChunk],
        embeddings: Sequence[Sequence[float]],
        *,
        provider: EmbeddingProvider | None = None,
        allowed_namespaces: Iterable[str] | None = None,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must be aligned")
        if vector_weight < 0 or keyword_weight < 0:
            raise ValueError("weights must be non-negative")
        if vector_weight + keyword_weight == 0:
            raise ValueError("at least one weight must be positive")

        self._chunks = list(chunks)
        self._embeddings = [list(vector) for vector in embeddings]
        self._provider: EmbeddingProvider = provider or HashEmbeddingProvider()
        self._vector_weight = vector_weight
        self._keyword_weight = keyword_weight
        namespaces = allowed_namespaces
        self._allowed: frozenset[str] | None = (
            frozenset(namespaces) if namespaces is not None else None
        )

    @classmethod
    async def build(
        cls,
        docs: Sequence[KnowledgeDoc],
        embeddings: EmbeddingProvider | None = None,
        *,
        allowed_namespaces: Iterable[str] | None = None,
        chunk_min_chars: int | None = None,
        chunk_max_chars: int | None = None,
    ) -> KnowledgeRetriever:
        """Chunk, embed, and index knowledge documents."""
        provider = embeddings or HashEmbeddingProvider()
        chunk_kwargs: dict[str, int] = {}
        if chunk_min_chars is not None:
            chunk_kwargs["min_chars"] = chunk_min_chars
        if chunk_max_chars is not None:
            chunk_kwargs["max_chars"] = chunk_max_chars
        chunks = chunk_documents(docs, **chunk_kwargs)
        vectors = await provider.embed([chunk.text for chunk in chunks]) if chunks else []
        return cls(chunks, vectors, provider=provider, allowed_namespaces=allowed_namespaces)

    @property
    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._chunks)

    @property
    def embedding_model(self) -> str:
        return self._provider.model_name

    def namespaces(self) -> list[str]:
        return sorted({chunk.namespace for chunk in self._chunks})

    def _authorize(self, namespaces: Sequence[str]) -> None:
        requested = [namespace.strip() for namespace in namespaces if namespace.strip()]
        if not requested:
            raise NamespaceAccessError("at least one namespace must be requested")
        if self._allowed is None:
            return
        for namespace in requested:
            permitted = any(_namespace_allows(namespace, allowed) for allowed in self._allowed)
            if not permitted:
                raise NamespaceAccessError(
                    f"namespace {namespace!r} is outside the permitted scopes"
                )

    async def retrieve(
        self,
        query: str,
        *,
        namespaces: Sequence[str],
        limit: int = DEFAULT_LIMIT,
    ) -> list[RetrievalHit]:
        """Retrieve the best chunks for ``query`` within the given namespaces."""
        if limit <= 0:
            raise ValueError("limit must be positive")
        self._authorize(namespaces)

        scoped = [
            (chunk, vector)
            for chunk, vector in zip(self._chunks, self._embeddings, strict=True)
            if any(_namespace_allows(namespace, chunk.namespace) for namespace in namespaces)
        ]
        if not scoped:
            return []

        query_vector = (await self._provider.embed([query]))[0]

        query_tokens = set(meaningful_tokens(query))
        query_lower = query.lower().strip()

        scored: list[RetrievalHit] = []
        for chunk, vector in scoped:
            vector_score = max(0.0, cosine_similarity(query_vector, vector))

            chunk_tokens = set(meaningful_tokens(chunk.text))
            overlap = len(query_tokens & chunk_tokens) / len(query_tokens) if query_tokens else 0.0
            phrase_bonus = 0.1 if query_lower and query_lower in chunk.text.lower() else 0.0
            keyword_score = min(1.0, overlap + phrase_bonus)

            score = self._vector_weight * vector_score + self._keyword_weight * keyword_score
            if score <= 0.0:
                continue
            scored.append(
                RetrievalHit(
                    chunk_id=chunk.id,
                    doc_id=chunk.doc_id,
                    title=chunk.title,
                    namespace=chunk.namespace,
                    heading_path=chunk.heading_path,
                    text=chunk.text,
                    score=round(score, 6),
                    vector_score=round(vector_score, 6),
                    keyword_score=round(keyword_score, 6),
                )
            )

        scored.sort(key=lambda hit: (-hit.score, hit.chunk_id))
        return scored[:limit]
