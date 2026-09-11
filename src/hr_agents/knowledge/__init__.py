"""Knowledge / RAG engine.

Retrieval powers recall, Q&A, and runbook grounding only. It is never used to
compute candidate scores — scoring remains deterministic and inspectable
(see ``docs/architecture/system-architecture.md``).
"""

from hr_agents.knowledge.chunking import KnowledgeChunk, chunk_document, chunk_documents
from hr_agents.knowledge.embeddings import (
    EmbeddingProvider,
    HashEmbeddingProvider,
    cosine_similarity,
)
from hr_agents.knowledge.retriever import (
    KnowledgeRetriever,
    NamespaceAccessError,
    RetrievalHit,
)

__all__ = [
    "EmbeddingProvider",
    "HashEmbeddingProvider",
    "KnowledgeChunk",
    "KnowledgeRetriever",
    "NamespaceAccessError",
    "RetrievalHit",
    "chunk_document",
    "chunk_documents",
    "cosine_similarity",
]
