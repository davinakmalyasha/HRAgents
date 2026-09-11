import pytest
from pydantic import ValidationError

from hr_agents.knowledge import KnowledgeChunk, chunk_document, chunk_documents
from hr_agents.skills.models import KnowledgeDoc


def make_doc(
    content: str, *, doc_id: str = "guide", namespace: str = "demo.sample"
) -> KnowledgeDoc:
    department = namespace.split(".")[0]
    return KnowledgeDoc(
        id=doc_id,
        title="Guide",
        department=department,
        namespace=namespace,
        source_path=f"skills/{department}/sample/knowledge/{doc_id}.md",
        content=content,
        content_hash="a" * 64,
    )


def test_sections_follow_heading_hierarchy() -> None:
    doc = make_doc(
        "# Top\nIntro text.\n\n## First\nFirst body.\n\n## Second\nSecond body.\n"
        "### Nested\nNested body.\n"
    )
    chunks = chunk_document(doc, min_chars=0, max_chars=10_000)

    paths = [chunk.heading_path for chunk in chunks]
    assert ["Top"] in paths
    assert ["Top", "First"] in paths
    assert ["Top", "Second"] in paths
    assert ["Top", "Second", "Nested"] in paths


def test_preamble_before_first_heading_becomes_chunk() -> None:
    doc = make_doc("Preamble paragraph.\n\n# Section\nBody.\n")
    chunks = chunk_document(doc, min_chars=0, max_chars=10_000)

    assert chunks[0].heading_path == []
    assert "Preamble paragraph." in chunks[0].text
    assert chunks[1].heading_path == ["Section"]


def test_headings_inside_code_fences_ignored() -> None:
    doc = make_doc("# Real\n\n```\n# not a heading\n```\n\nAfter.\n")
    chunks = chunk_document(doc, min_chars=0, max_chars=10_000)

    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Real"]
    assert "# not a heading" in chunks[0].text


def test_small_section_merges_upward() -> None:
    doc = make_doc("# Parent\n" + ("A long paragraph. " * 30) + "\n\n## Tiny\nOne line.\n")
    chunks = chunk_document(doc, min_chars=200, max_chars=2_000)

    assert len(chunks) == 1
    assert "One line." in chunks[0].text


def test_oversized_section_splits_at_paragraphs() -> None:
    body = "\n\n".join(f"Paragraph {index} " + ("word " * 40) for index in range(12))
    doc = make_doc(f"# Big\n\n{body}\n")
    chunks = chunk_document(doc, min_chars=0, max_chars=600)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 650 for chunk in chunks)
    assert all(chunk.heading_path == ["Big"] for chunk in chunks)


def test_line_spans_are_ordered_and_valid() -> None:
    doc = make_doc("# A\nLine one.\n\n# B\nLine two.\n")
    chunks = chunk_document(doc, min_chars=0, max_chars=10_000)

    for chunk in chunks:
        assert 1 <= chunk.start_line <= chunk.end_line
    assert chunks[0].start_line < chunks[1].start_line


def test_chunk_ids_are_deterministic() -> None:
    doc = make_doc("# A\nText.\n\n# B\nMore.\n")
    first = chunk_document(doc, min_chars=0, max_chars=10_000)
    second = chunk_document(doc, min_chars=0, max_chars=10_000)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]
    assert [chunk.id for chunk in first] == ["guide#0", "guide#1"]


def test_citation_includes_breadcrumb() -> None:
    doc = make_doc("# Top\nIntro.\n\n## Leaf\nDetails.\n")
    chunks = chunk_document(doc, min_chars=0, max_chars=10_000)
    citation = next(chunk for chunk in chunks if chunk.heading_path == ["Top", "Leaf"]).citation()

    assert "Guide" in citation
    assert "Top > Leaf" in citation


def test_chunk_documents_sorted_by_namespace_and_id() -> None:
    docs = [
        make_doc("# B\nText.\n", doc_id="z", namespace="b.demo"),
        make_doc("# A\nText.\n", doc_id="a", namespace="a.demo"),
    ]
    chunks = chunk_documents(docs, min_chars=0, max_chars=10_000)

    assert [chunk.namespace for chunk in chunks] == ["a.demo", "b.demo"]


def test_invalid_parameters_rejected() -> None:
    doc = make_doc("# A\nText.\n")
    for kwargs in ({"min_chars": -1}, {"max_chars": 0}):
        try:
            chunk_document(doc, **kwargs)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {kwargs}")


def test_whitespace_only_document_rejected_by_model() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        make_doc("\n\n")


def test_chunk_is_a_strict_model() -> None:
    chunk = KnowledgeChunk(
        id="x#0",
        doc_id="x",
        title="X",
        department="demo",
        namespace="demo.sample",
        heading_path=[],
        text="text",
    )
    assert chunk.start_line == 1
