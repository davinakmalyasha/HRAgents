import math

import pytest

from hr_agents.knowledge.embeddings import (
    HashEmbeddingProvider,
    cosine_similarity,
    meaningful_tokens,
    tokenize,
)


async def test_embedding_is_deterministic_across_instances() -> None:
    first = HashEmbeddingProvider(dimension=128)
    second = HashEmbeddingProvider(dimension=128)

    a = await first.embed(["Backend engineer with PostgreSQL experience"])
    b = await second.embed(["Backend engineer with PostgreSQL experience"])

    assert a == b


async def test_embedding_dimension_and_normalization() -> None:
    provider = HashEmbeddingProvider(dimension=64)
    vector = (await provider.embed(["kubernetes docker redis"]))[0]

    assert len(vector) == 64
    norm = math.sqrt(sum(value * value for value in vector))
    assert norm == pytest.approx(1.0)


async def test_different_texts_differ() -> None:
    provider = HashEmbeddingProvider(dimension=128)
    first, second = await provider.embed(["payroll and BPJS rules", "interview scheduling"])

    assert first != second
    assert cosine_similarity(first, second) < 0.99


async def test_similar_text_scores_higher_than_unrelated() -> None:
    provider = HashEmbeddingProvider(dimension=512)
    query, near, far = await provider.embed(
        [
            "Docker container deployment",
            "Docker containers and deployment pipelines",
            "leave policy annual holiday",
        ]
    )

    assert cosine_similarity(query, near) > cosine_similarity(query, far)


async def test_empty_text_yields_zero_vector() -> None:
    provider = HashEmbeddingProvider(dimension=32)
    vector = (await provider.embed([""]))[0]

    assert vector == [0.0] * 32
    assert cosine_similarity(vector, vector) == 0.0


async def test_batch_embedding_aligns_with_input() -> None:
    provider = HashEmbeddingProvider(dimension=32)
    vectors = await provider.embed(["one", "two", "three"])

    assert len(vectors) == 3
    assert len({tuple(vector) for vector in vectors}) == 3


def test_cosine_similarity_math() -> None:
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_similarity_dimension_mismatch() -> None:
    with pytest.raises(ValueError, match="same dimension"):
        cosine_similarity([1.0], [1.0, 2.0])


def test_model_name_includes_dimension() -> None:
    assert HashEmbeddingProvider(dimension=256).model_name == "hash-bow-v1-256"


def test_invalid_dimension_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        HashEmbeddingProvider(dimension=0)


def test_tokenization() -> None:
    assert tokenize("PostgreSQL 16 & FastAPI!") == ["postgresql", "16", "fastapi"]


def test_stopword_filtering() -> None:
    assert meaningful_tokens("how to apply for leave and the process") == [
        "how",
        "apply",
        "leave",
        "process",
    ]
    assert meaningful_tokens("cuti dan izin yang di ajukan") == ["cuti", "izin", "ajukan"]
