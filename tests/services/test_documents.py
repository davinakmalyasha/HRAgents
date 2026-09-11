from hr_agents.services.documents import (
    extract_text,
    guess_kind,
    redact_pii,
    sha256_bytes,
)


def _build_minimal_pdf(text: str) -> bytes:
    """Assemble a tiny valid PDF with correct xref offsets."""
    content = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        b"<< /Length "
        + str(len(content)).encode()
        + b" >>\nstream\n"
        + content.encode()
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode()
    return bytes(out)


def test_sha256_deterministic() -> None:
    assert sha256_bytes(b"hragents") == sha256_bytes(b"hragents")
    assert sha256_bytes(b"a") != sha256_bytes(b"b")
    assert len(sha256_bytes(b"x")) == 64


def test_guess_kind() -> None:
    assert guess_kind("cv_budi.pdf") == "cv"
    assert guess_kind("profile.json") == "linkedin_export"
    assert guess_kind("notes.txt") == "other"
    assert guess_kind("archive.bin") == "other"


def test_extract_text_plain() -> None:
    assert extract_text(b"Hello HRAgents", "cv.txt") == "Hello HRAgents"


def test_extract_text_pdf() -> None:
    pdf = _build_minimal_pdf("Hello HRAgents")
    extracted = extract_text(pdf, "cv.pdf")
    assert "Hello HRAgents" in extracted


def test_redact_email() -> None:
    result = redact_pii("Contact budi.santoso@example.com for details")
    assert "[EMAIL]" in result.text
    assert "budi.santoso@example.com" not in result.text
    assert result.counts["email"] == 1


def test_redact_indonesian_nik() -> None:
    result = redact_pii("NIK: 3174092501990003 on file")
    assert result.text == "NIK: [ID_NUMBER] on file"
    assert result.counts["id_number"] == 1


def test_redact_phone() -> None:
    result = redact_pii("Call +62 812-3456-7890 tomorrow")
    assert "[PHONE]" in result.text
    assert result.counts["phone"] == 1


def test_redact_does_not_eat_dates() -> None:
    result = redact_pii("Worked 2020-2024 on backend systems")
    assert "2020-2024" in result.text
    assert result.counts["phone"] == 0


def test_redact_multiple_identifiers() -> None:
    text = "Email a@b.co, phone +62 811 223 344, NIK 3174092501990003"
    result = redact_pii(text)
    assert result.counts["email"] == 1
    assert result.counts["phone"] == 1
    assert result.counts["id_number"] == 1
    assert result.total_redacted == 3
