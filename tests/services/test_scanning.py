"""The malware-scanning contract: honest outcomes, bounded transport."""

from __future__ import annotations

import struct

import pytest

from hr_agents.services.scanning import (
    ClamAvScanner,
    NoopScanner,
    ScanOutcome,
    ScanResult,
    build_scanner,
)


class FakeConnection:
    def __init__(self, response: bytes) -> None:
        self.sent = bytearray()
        self.response = response
        self.closed = False

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def recv(self, size: int) -> bytes:
        chunk = self.response[:size]
        self.response = self.response[size:]
        return chunk

    def close(self) -> None:
        self.closed = True


def scanner(response: bytes) -> tuple[ClamAvScanner, FakeConnection]:
    connection = FakeConnection(response)
    return (
        ClamAvScanner(host="clamav", connect=lambda address, timeout: connection),
        connection,
    )


def test_no_scanner_says_it_did_not_scan() -> None:
    result = NoopScanner().scan(b"hello", filename="cv.pdf")

    assert result.outcome is ScanOutcome.DISABLED
    assert "not scanned" in result.detail


def test_clean_bytes_are_framed_as_instream_and_reported_clean() -> None:
    clam, connection = scanner(b"stream: OK\0")

    result = clam.scan(b"hello world")

    assert result.outcome is ScanOutcome.CLEAN
    assert connection.sent.startswith(b"zINSTREAM\0")
    assert connection.sent.endswith(struct.pack("!I", 0))
    assert struct.pack("!I", 11) + b"hello world" in bytes(connection.sent)
    assert connection.closed is True


def test_a_signature_is_infected_and_named_without_the_payload() -> None:
    clam, _ = scanner(b"stream: Eicar-Test-Signature FOUND\0")

    result = clam.scan(b"hello")

    assert result.outcome is ScanOutcome.INFECTED
    assert result.detail == "Eicar-Test-Signature"


def test_an_unexpected_answer_is_unavailable_not_clean() -> None:
    clam, _ = scanner(b"stream: SOMETHING\0")

    assert clam.scan(b"hello").outcome is ScanOutcome.UNAVAILABLE


def test_a_transport_failure_is_unavailable_not_an_exception() -> None:
    def refuse(address: tuple[str, int], timeout: float) -> FakeConnection:
        raise OSError("connection refused")

    clam = ClamAvScanner(host="clamav", connect=refuse)

    result = clam.scan(b"hello")

    assert result.outcome is ScanOutcome.UNAVAILABLE
    assert "OSError" in result.detail


def test_configuration_is_validated() -> None:
    with pytest.raises(ValueError):
        ClamAvScanner(host="")
    with pytest.raises(ValueError):
        ClamAvScanner(host="clamav", port=0)


def test_the_factory_is_off_unless_a_host_is_configured() -> None:
    class Off:
        clamav_host = ""

    class On:
        clamav_host = "localhost"
        clamav_port = 3310
        clamav_timeout = 1.0

    assert isinstance(build_scanner(Off()), NoopScanner)
    assert isinstance(build_scanner(On()), ClamAvScanner)


def test_a_scan_result_names_its_scanner() -> None:
    assert ScanResult(outcome=ScanOutcome.CLEAN, scanner="clamav").scanner == "clamav"
