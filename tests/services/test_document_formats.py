"""Magic-byte validation: the filename is a claim, the bytes are the fact."""

from __future__ import annotations

import io
import zipfile

import pytest

from hr_agents.services.documents import (
    DocumentFormat,
    DocumentFormatError,
    detect_document_format,
    ensure_supported_document,
)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/>'
    "</Types>"
)


def build_docx(*paragraphs: str, entry: str = "word/document.xml") -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr(entry, document)
    return buffer.getvalue()


def test_pdf_magic_is_detected() -> None:
    assert detect_document_format(b"%PDF-1.7\n...") is DocumentFormat.PDF


def test_docx_is_detected_by_its_document_entry() -> None:
    assert detect_document_format(build_docx("Sari Dewi")) is DocumentFormat.DOCX


def test_a_zip_without_a_word_document_is_not_a_docx() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("photos/image.png", b"\x89PNG")

    assert detect_document_format(buffer.getvalue()) is None


def test_plain_text_is_detected() -> None:
    assert detect_document_format(b"Budi Santoso\nBackend engineer") is DocumentFormat.TEXT


def test_binary_with_nuls_is_not_text() -> None:
    assert detect_document_format(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR") is None


def test_a_mislabelled_pdf_is_refused() -> None:
    with pytest.raises(DocumentFormatError, match="not a PDF"):
        ensure_supported_document("cv.pdf", b"this is plain text")


def test_a_mislabelled_docx_is_refused() -> None:
    with pytest.raises(DocumentFormatError, match="not a DOCX"):
        ensure_supported_document("cv.docx", b"this is plain text")


def test_legacy_binary_office_files_are_refused_with_guidance() -> None:
    with pytest.raises(DocumentFormatError, match="save the document as PDF or DOCX"):
        ensure_supported_document("cv.doc", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


def test_an_unknown_binary_is_refused() -> None:
    with pytest.raises(DocumentFormatError, match="not a supported document"):
        ensure_supported_document("cv.bin", b"\x7fELF\x02\x01\x01\x00")


def test_a_matching_file_is_accepted() -> None:
    assert ensure_supported_document("cv.txt", b"Budi") is DocumentFormat.TEXT
    assert ensure_supported_document("cv.pdf", b"%PDF-1.4\n") is DocumentFormat.PDF
    assert ensure_supported_document("cv.docx", build_docx("Sari")) is DocumentFormat.DOCX


def test_an_extensionless_file_is_judged_by_its_bytes() -> None:
    assert ensure_supported_document(None, b"Budi") is DocumentFormat.TEXT
    with pytest.raises(DocumentFormatError):
        ensure_supported_document(None, b"\x00\x01\x02")
