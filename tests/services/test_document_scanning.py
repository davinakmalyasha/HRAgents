"""Uploads pass the scanner before anything is stored."""

from __future__ import annotations

import pytest

from hr_agents.identity import ActorRef
from hr_agents.services.recruiting import (
    DocumentInfectedError,
    DocumentScanUnavailableError,
    DocumentService,
)
from hr_agents.services.scanning import NoopScanner, ScanOutcome, ScanResult

HUMAN = ActorRef.legacy("recruiter")


class FixedScanner:
    def __init__(self, outcome: ScanOutcome, detail: str = "") -> None:
        self._result = ScanResult(outcome=outcome, scanner="fake", detail=detail)

    def scan(self, content: bytes, *, filename: str | None = None) -> ScanResult:
        return self._result


def upload(service: DocumentService):  # type: ignore[no-untyped-def]
    return service.upload(filename="cv.pdf", kind="cv", content=b"a candidate's cv", actor=HUMAN)


def test_no_scanner_stores_the_file_and_records_that_it_was_unscanned() -> None:
    service = DocumentService(scanner=NoopScanner())

    document = upload(service)

    assert service.get(document.id).sha256 == document.sha256
    payload = service._audit.entries[-1].payload
    assert payload["scan"] == "disabled"


def test_clean_bytes_are_stored_with_the_scan_outcome_on_the_chain() -> None:
    service = DocumentService(scanner=FixedScanner(ScanOutcome.CLEAN))

    document = upload(service)

    assert service.get(document.id).filename == "cv.pdf"
    assert service._audit.entries[-1].payload["scan"] == "clean"


def test_infected_bytes_are_refused_and_never_stored() -> None:
    service = DocumentService(
        scanner=FixedScanner(ScanOutcome.INFECTED, detail="Eicar-Test-Signature")
    )

    with pytest.raises(DocumentInfectedError, match="malware"):
        upload(service)

    assert service.list_all() == []
    entry = service._audit.entries[-1]
    assert entry.action == "document.rejected_malware"
    assert entry.payload["signature"] == "Eicar-Test-Signature"
    assert "a candidate" not in str(entry.payload)


def test_a_configured_but_unavailable_scanner_refuses_the_upload() -> None:
    service = DocumentService(scanner=FixedScanner(ScanOutcome.UNAVAILABLE))

    with pytest.raises(DocumentScanUnavailableError, match="unavailable"):
        upload(service)

    assert service.list_all() == []
    assert service._audit.entries[-1].action == "document.scan_unavailable"
