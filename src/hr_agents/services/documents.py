"""Document ingestion: hashing, text extraction, and PII redaction.

Redaction is best-effort and runs **before** any LLM call. It is a privacy
layer, not a compliance guarantee — extraction metadata records what was
redacted so downstream stages can reason about it.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_NIK_RE = re.compile(r"(?<!\d)\d{16}(?!\d)")
_PHONE_RE = re.compile(r"(?<![\d-])(?:\+?\d[\d\s\-()]{7,16}\d)(?!\d)")

_EMAIL_TOKEN = "[EMAIL]"
_NIK_TOKEN = "[ID_NUMBER]"
_PHONE_TOKEN = "[PHONE]"

_KIND_BY_SUFFIX = {
    ".pdf": "cv",
    ".docx": "cv",
    ".doc": "cv",
    ".txt": "other",
    ".md": "other",
    ".json": "linkedin_export",
}


@dataclass
class RedactionResult:
    """Redacted text plus counts of what was removed (for the audit trail)."""

    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total_redacted(self) -> int:
        return sum(self.counts.values())


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw document bytes."""
    return hashlib.sha256(data).hexdigest()


def guess_kind(filename: str) -> str:
    """Best-effort document kind from filename."""
    suffix = Path(filename).suffix.lower()
    return _KIND_BY_SUFFIX.get(suffix, "other")


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value)


def redact_pii(text: str) -> RedactionResult:
    """Replace likely personal identifiers with typed tokens."""
    counts = {"email": 0, "id_number": 0, "phone": 0}

    def _email(match: re.Match[str]) -> str:
        counts["email"] += 1
        return _EMAIL_TOKEN

    def _nik(match: re.Match[str]) -> str:
        counts["id_number"] += 1
        return _NIK_TOKEN

    def _phone(match: re.Match[str]) -> str:
        digits = _digits_only(match.group(0))
        if 9 <= len(digits) <= 15:
            counts["phone"] += 1
            return _PHONE_TOKEN
        return match.group(0)

    text = _EMAIL_RE.sub(_email, text)
    text = _NIK_RE.sub(_nik, text)
    text = _PHONE_RE.sub(_phone, text)
    return RedactionResult(text=text, counts=counts)


MAX_EXTRACTED_CHARS = 200_000
"""How much text one document may contribute to an evaluation."""

MAX_EXTRACTED_PAGES = 200
"""How many pages of a PDF are read. A page bomb is a denial of service, not a CV."""


@dataclass(frozen=True)
class ExtractedText:
    """Extracted text, and whether it is the whole document.

    The flag is the point. A CV that was cut short is not a shorter CV; it is a
    document whose middle is missing, and scoring it as if it were complete
    would quietly understate a candidate. Callers pass the flag on, and the
    evaluation routes to a person instead of a score.
    """

    text: str
    truncated: bool


def extract_document(data: bytes, filename: str = "") -> ExtractedText:
    """Extract plain text from a document, bounded.

    PDFs are parsed with pypdf; text-like files are decoded as UTF-8 with
    replacement. Both are cut at ``MAX_EXTRACTED_CHARS``, and a PDF at
    ``MAX_EXTRACTED_PAGES`` pages: a 10 MiB file of ten thousand pages would
    otherwise cost minutes of parsing and produce a CV that is quietly missing
    its middle.
    """
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        total = 0
        truncated = False
        for index, page in enumerate(reader.pages):
            if index >= MAX_EXTRACTED_PAGES:
                truncated = True
                break
            page_text = page.extract_text() or ""
            pages.append(page_text)
            total += len(page_text)
            if total >= MAX_EXTRACTED_CHARS:
                truncated = index + 1 < len(reader.pages)
                break
        return ExtractedText("\n".join(pages).strip()[:MAX_EXTRACTED_CHARS], truncated)
    decoded = data.decode("utf-8", errors="replace").strip()
    if len(decoded) > MAX_EXTRACTED_CHARS:
        return ExtractedText(decoded[:MAX_EXTRACTED_CHARS], True)
    return ExtractedText(decoded, False)


def extract_text(data: bytes, filename: str = "") -> str:
    """Extract plain text from a document (see :func:`extract_document`)."""
    return extract_document(data, filename).text
