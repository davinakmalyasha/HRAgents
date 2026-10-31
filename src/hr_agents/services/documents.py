"""Document ingestion: hashing, text extraction, and PII redaction.

Redaction is best-effort and runs **before** any LLM call. It is a privacy
layer, not a compliance guarantee — extraction metadata records what was
redacted so downstream stages can reason about it.
"""

from __future__ import annotations

import codecs
import hashlib
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from enum import StrEnum
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


class DocumentFormat(StrEnum):
    """A format this product can actually extract text from."""

    PDF = "pdf"
    DOCX = "docx"
    TEXT = "text"


class DocumentFormatError(ValueError):
    """The upload is not a document this product can read."""


_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_DOCX_DOCUMENT = "word/document.xml"
_SUFFIX_FORMATS = {
    ".pdf": DocumentFormat.PDF,
    ".docx": DocumentFormat.DOCX,
    ".txt": DocumentFormat.TEXT,
    ".md": DocumentFormat.TEXT,
    ".json": DocumentFormat.TEXT,
    ".csv": DocumentFormat.TEXT,
}
_LEGACY_BINARY_SUFFIXES = frozenset({".doc", ".xls", ".ppt"})
_FORMAT_LABELS = {
    DocumentFormat.PDF: "PDF",
    DocumentFormat.DOCX: "DOCX",
    DocumentFormat.TEXT: "text document",
}


def _looks_textual(content: bytes) -> bool:
    """UTF-8 text with no NULs and only a sliver of control characters."""
    if content.startswith(codecs.BOM_UTF8):
        content = content[len(codecs.BOM_UTF8) :]
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return False
    if text == "":
        return True
    if "\x00" in text:
        return False
    printable = sum(1 for char in text if char.isprintable() or char in "\r\n\t")
    return printable / len(text) >= 0.95


def _is_docx(content: bytes) -> bool:
    if not content.startswith(_ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return _DOCX_DOCUMENT in archive.namelist()
    except zipfile.BadZipFile, OSError:
        return False


def detect_document_format(content: bytes) -> DocumentFormat | None:
    """The format the bytes actually are, not what the filename claims."""
    if content.startswith(_PDF_MAGIC):
        return DocumentFormat.PDF
    if _is_docx(content):
        return DocumentFormat.DOCX
    if _looks_textual(content):
        return DocumentFormat.TEXT
    return None


def ensure_supported_document(filename: str | None, content: bytes) -> DocumentFormat:
    """Refuse bytes the extractor cannot read, and refuse a mislabelled file.

    ``kind`` on the upload form is a business label (cv, portfolio, ...), not a
    format, so it cannot be trusted to describe the bytes. The suffix is a
    weaker claim than the magic bytes, and when the two disagree the upload is
    refused rather than handing an executable or an image to a text parser.
    """
    suffix = Path(filename).suffix.lower() if filename else ""
    if suffix in _LEGACY_BINARY_SUFFIXES:
        raise DocumentFormatError(
            f"{suffix} files are not supported; save the document as PDF or DOCX"
        )
    detected = detect_document_format(content)
    if detected is None:
        raise DocumentFormatError(
            "the uploaded file is not a supported document; use PDF, DOCX, or UTF-8 text"
        )
    expected = _SUFFIX_FORMATS.get(suffix)
    if expected is not None and detected is not expected:
        raise DocumentFormatError(
            f"filename ends in {suffix} but the content is not a {_FORMAT_LABELS[expected]}"
        )
    return detected


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


_DOCX_TEXT_RE = re.compile(rb"<w:t(?:\s[^>]*)?>(.*?)</w:t>", re.DOTALL)
MAX_DOCX_XML_BYTES = 20 * 1024 * 1024
"""Uncompressed size ceiling for one DOCX body; the upload limit bounds the zip,
not what its deflate stream expands to."""


def _extract_docx(data: bytes) -> ExtractedText:
    """DOCX paragraphs from ``word/document.xml`` without an XML parser.

    The archive comes from an upload, so the XML is untrusted: scanning the
    text runs with a bounded regex avoids entity-expansion attacks an XML
    parser would have to defend against. ZIP entry names are stored plainly,
    so the document entry is found without decompressing the rest.
    """
    try:
        with (
            zipfile.ZipFile(io.BytesIO(data)) as archive,
            archive.open(_DOCX_DOCUMENT) as stream,
        ):
            raw = stream.read(MAX_DOCX_XML_BYTES + 1)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ValueError("not a readable DOCX document") from exc
    truncated = len(raw) > MAX_DOCX_XML_BYTES
    raw = raw[:MAX_DOCX_XML_BYTES]
    paragraphs: list[str] = []
    for chunk in raw.split(b"</w:p>"):
        runs = [
            html.unescape(match.group(1).decode("utf-8", errors="replace"))
            for match in _DOCX_TEXT_RE.finditer(chunk)
        ]
        if runs:
            paragraphs.append("".join(runs))
    text = "\n".join(paragraphs).strip()
    if len(text) > MAX_EXTRACTED_CHARS:
        return ExtractedText(text[:MAX_EXTRACTED_CHARS], True)
    return ExtractedText(text, truncated)


def extract_document(data: bytes, filename: str = "") -> ExtractedText:
    """Extract plain text from a document, bounded.

    PDFs are parsed with pypdf, DOCX bodies from ``word/document.xml``, and
    text-like files decoded as UTF-8 with replacement. All are cut at
    ``MAX_EXTRACTED_CHARS``, and a PDF at ``MAX_EXTRACTED_PAGES`` pages: a 10 MiB
    file of ten thousand pages would otherwise cost minutes of parsing and
    produce a CV that is quietly missing its middle.
    """
    detected = detect_document_format(data)
    if detected is DocumentFormat.PDF or (detected is None and filename.lower().endswith(".pdf")):
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
    if detected is DocumentFormat.DOCX or filename.lower().endswith(".docx"):
        return _extract_docx(data)
    decoded = data.decode("utf-8", errors="replace").strip()
    if len(decoded) > MAX_EXTRACTED_CHARS:
        return ExtractedText(decoded[:MAX_EXTRACTED_CHARS], True)
    return ExtractedText(decoded, False)


def extract_text(data: bytes, filename: str = "") -> str:
    """Extract plain text from a document (see :func:`extract_document`)."""
    return extract_document(data, filename).text
