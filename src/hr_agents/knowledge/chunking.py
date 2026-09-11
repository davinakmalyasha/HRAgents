"""Heading-aware markdown chunking with source spans.

Each chunk carries its heading path (breadcrumb), line span, and namespace so
retrieval results are citable and auditable down to the section level.

Chunking rules:
- sections split at markdown headings (outside fenced code blocks)
- very small sections merge upward into the previous chunk when they share a
  heading prefix and the result stays within ``max_chars``
- oversized sections split at paragraph boundaries, each part keeping the
  section's heading path
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from hr_agents.models import StrictModel
from hr_agents.skills.models import KnowledgeDoc

DEFAULT_MIN_CHARS = 200
DEFAULT_MAX_CHARS = 1200

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


class KnowledgeChunk(StrictModel):
    """A retrievable unit of knowledge with full citation metadata."""

    id: str
    doc_id: str
    title: str
    department: str
    namespace: str
    heading_path: list[str]
    text: str
    start_line: int = 1
    end_line: int = 1

    def citation(self) -> str:
        """Human-readable citation string."""
        breadcrumb = " > ".join(self.heading_path) if self.heading_path else self.title
        return f"{self.title} — {breadcrumb} ({self.doc_id})"


class _Section:
    __slots__ = ("heading_path", "lines", "start_line")

    def __init__(self, heading_path: list[str], start_line: int) -> None:
        self.heading_path = heading_path
        self.lines: list[str] = []
        self.start_line = start_line

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _split_sections(content: str) -> list[_Section]:
    lines = content.splitlines()
    sections: list[_Section] = []
    heading_stack: list[tuple[int, str]] = []
    current = _Section([], 1)
    in_fence = False

    for index, line in enumerate(lines, start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            current.lines.append(line)
            continue

        heading = None if in_fence else _HEADING_RE.match(line)
        if heading is None:
            current.lines.append(line)
            continue

        if current.text:
            sections.append(current)

        level = len(heading.group(1))
        title = heading.group(2)
        heading_stack = [item for item in heading_stack if item[0] < level]
        heading_stack.append((level, title))
        current = _Section([title for _, title in heading_stack], index)
        current.lines.append(line)

    if current.text:
        sections.append(current)

    return sections


def _is_prefix(prefix: list[str], path: list[str]) -> bool:
    return len(prefix) <= len(path) and path[: len(prefix)] == prefix


def _merge_sections(
    sections: Sequence[_Section], *, min_chars: int, max_chars: int
) -> list[_Section]:
    merged: list[_Section] = []
    for section in sections:
        if (
            merged
            and len(section.text) < min_chars
            and _is_prefix(merged[-1].heading_path, section.heading_path)
            and len(merged[-1].text) + len(section.text) + 1 <= max_chars
        ):
            merged[-1].lines.append("")
            merged[-1].lines.extend(section.lines)
            continue
        merged.append(section)
    return merged


def _split_oversized(section: _Section, *, max_chars: int) -> list[_Section]:
    if len(section.text) <= max_chars:
        return [section]

    parts: list[_Section] = []
    buffer: list[str] = []
    buffer_size = 0
    part_start = section.start_line

    for offset, line in enumerate(section.lines):
        line_size = len(line) + 1
        if buffer and buffer_size + line_size > max_chars:
            part = _Section(list(section.heading_path), part_start)
            part.lines = buffer
            parts.append(part)
            part_start = section.start_line + offset
            buffer = []
            buffer_size = 0
        buffer.append(line)
        buffer_size += line_size

    if buffer:
        part = _Section(list(section.heading_path), part_start)
        part.lines = buffer
        parts.append(part)

    return parts


def chunk_document(
    doc: KnowledgeDoc,
    *,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[KnowledgeChunk]:
    """Chunk one knowledge document deterministically."""
    if min_chars < 0:
        raise ValueError("min_chars must be non-negative")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    sections: list[_Section] = []
    for section in _merge_sections(
        _split_sections(doc.content), min_chars=min_chars, max_chars=max_chars
    ):
        sections.extend(_split_oversized(section, max_chars=max_chars))

    chunks: list[KnowledgeChunk] = []
    for index, section in enumerate(sections):
        text = section.text
        if not text:
            continue
        end_line = section.start_line + len(section.lines) - 1
        chunks.append(
            KnowledgeChunk(
                id=f"{doc.id}#{index}",
                doc_id=doc.id,
                title=doc.title,
                department=doc.department,
                namespace=doc.namespace,
                heading_path=section.heading_path,
                text=text,
                start_line=section.start_line,
                end_line=max(end_line, section.start_line),
            )
        )
    return chunks


def chunk_documents(
    docs: Sequence[KnowledgeDoc],
    *,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[KnowledgeChunk]:
    """Chunk many documents, ordered deterministically by namespace/id."""
    ordered = sorted(docs, key=lambda doc: (doc.namespace, doc.id))
    chunks: list[KnowledgeChunk] = []
    for doc in ordered:
        chunks.extend(chunk_document(doc, min_chars=min_chars, max_chars=max_chars))
    return chunks
