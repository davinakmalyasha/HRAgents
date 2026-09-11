from pathlib import Path

import pytest

from hr_agents.knowledge import (
    HashEmbeddingProvider,
    KnowledgeRetriever,
    NamespaceAccessError,
)
from hr_agents.skills import SkillRegistry, load_library

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = REPO_ROOT / "skills"


@pytest.fixture
async def repo_retriever() -> KnowledgeRetriever:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    return await KnowledgeRetriever.build(registry.knowledge())


@pytest.fixture
async def scoped_retriever() -> KnowledgeRetriever:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    return await KnowledgeRetriever.build(
        registry.knowledge(),
        allowed_namespaces=registry.knowledge_namespaces(),
    )


async def test_retrieve_returns_citable_hits(repo_retriever: KnowledgeRetriever) -> None:
    hits = await repo_retriever.retrieve(
        "backend engineer technical depth rubric", namespaces=["recruiting.evaluation"]
    )

    assert hits
    top = hits[0]
    assert top.namespace == "recruiting.evaluation"
    assert top.doc_id
    assert top.heading_path
    assert "(" in top.citation()


async def test_relevant_outranks_unrelated(repo_retriever: KnowledgeRetriever) -> None:
    hits = await repo_retriever.retrieve(
        "systems literacy architecture queues caching", namespaces=["recruiting.evaluation"]
    )

    top_ids = [hit.doc_id for hit in hits[:2]]
    assert "backend-rubric" in top_ids


async def test_retrieval_is_deterministic(repo_retriever: KnowledgeRetriever) -> None:
    query = "certification verification cloud"
    first = await repo_retriever.retrieve(query, namespaces=["recruiting.evaluation"])
    second = await repo_retriever.retrieve(query, namespaces=["recruiting.evaluation"])

    assert [hit.chunk_id for hit in first] == [hit.chunk_id for hit in second]


async def test_namespace_scope_excludes_other_departments(
    repo_retriever: KnowledgeRetriever,
) -> None:
    hits = await repo_retriever.retrieve(
        "consent data protection personal data", namespaces=["recruiting.evaluation"]
    )

    assert all(hit.namespace == "recruiting.evaluation" for hit in hits)


async def test_platform_namespace_retrievable_when_requested(
    repo_retriever: KnowledgeRetriever,
) -> None:
    hits = await repo_retriever.retrieve(
        "consent data protection UU PDP", namespaces=["platform.compliance"]
    )

    assert hits
    assert all(hit.namespace == "platform.compliance" for hit in hits)


async def test_parent_namespace_includes_children(repo_retriever: KnowledgeRetriever) -> None:
    hits = await repo_retriever.retrieve("feedback template strengths", namespaces=["recruiting"])

    namespaces = {hit.namespace for hit in hits}
    assert namespaces <= {"recruiting.evaluation", "recruiting.feedback"}


async def test_limit_respected(repo_retriever: KnowledgeRetriever) -> None:
    hits = await repo_retriever.retrieve("engineer", namespaces=["recruiting.evaluation"], limit=1)
    assert len(hits) <= 1


async def test_empty_namespaces_rejected(repo_retriever: KnowledgeRetriever) -> None:
    with pytest.raises(NamespaceAccessError, match="at least one namespace"):
        await repo_retriever.retrieve("anything", namespaces=[])


async def test_unpermitted_namespace_rejected(scoped_retriever: KnowledgeRetriever) -> None:
    with pytest.raises(NamespaceAccessError, match="outside the permitted scopes"):
        await scoped_retriever.retrieve("payroll", namespaces=["finance.payroll"])


async def test_no_matches_returns_empty(repo_retriever: KnowledgeRetriever) -> None:
    hits = await repo_retriever.retrieve("zzzzz qqqq xxxx", namespaces=["recruiting.evaluation"])
    assert hits == []


async def test_custom_embedding_provider_binds_at_build() -> None:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    provider = HashEmbeddingProvider(dimension=64)
    retriever = await KnowledgeRetriever.build(registry.knowledge(), provider)

    assert retriever.embedding_model == "hash-bow-v1-64"
    hits = await retriever.retrieve("backend rubric", namespaces=["recruiting.evaluation"])
    assert hits


async def test_build_with_custom_chunking() -> None:
    registry = SkillRegistry(load_library(SKILLS_ROOT))
    retriever = await KnowledgeRetriever.build(
        registry.knowledge(), chunk_min_chars=0, chunk_max_chars=400
    )
    assert len(retriever.chunks) >= len(registry.knowledge())
    assert retriever.namespaces()


async def test_constructor_alignment_validation() -> None:
    with pytest.raises(ValueError, match="aligned"):
        KnowledgeRetriever([], [[0.0]])
    with pytest.raises(ValueError, match="non-negative"):
        KnowledgeRetriever([], [], vector_weight=-1.0)
    with pytest.raises(ValueError, match="at least one weight"):
        KnowledgeRetriever([], [], vector_weight=0.0, keyword_weight=0.0)


async def test_invalid_limit_rejected(repo_retriever: KnowledgeRetriever) -> None:
    with pytest.raises(ValueError, match="limit"):
        await repo_retriever.retrieve("x", namespaces=["recruiting.evaluation"], limit=0)
