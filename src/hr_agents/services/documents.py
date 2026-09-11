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


def extract_text(data: bytes, filename: str = "") -> str:
    """Extract plain text from a document.

    PDFs are parsed with pypdf; text-like files are decoded as UTF-8 with
    replacement. Unsupported binaries decode best-effort.
    """
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        reader = PdfReader(io.BytesIO(data))
        pages: list[str] = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        return "\n".join(pages).strip()
    return data.decode("utf-8", errors="replace").strip()
