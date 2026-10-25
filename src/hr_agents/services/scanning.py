"""Malware scanning for uploaded documents.

The upload path is the one place an attacker can put arbitrary bytes into the
system, so the gate belongs there and it must be explicit about what it did:

- **disabled** — no scanner configured. The file is stored (the product runs
  offline by default) and the audit entry says it was not scanned.
- **clean** — the scanner answered; the file may be stored.
- **infected** — refused; the bytes are never persisted, and the refusal is
  audited without the content or the filename.
- **unavailable** — a scanner was configured but did not answer. The upload is
  refused rather than stored unscanned: an operator who configured a scanner
  asked for that guarantee, and silently downgrading it is the failure mode this
  module exists to prevent.
"""

from __future__ import annotations

import socket
import struct
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from pydantic import Field

from hr_agents.models import StrictModel

CHUNK_SIZE = 8192


class ScanOutcome(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class ScanResult(StrictModel):
    """What the scanner said, and which scanner said it."""

    outcome: ScanOutcome
    scanner: str = Field(min_length=1, max_length=60)
    detail: str = Field(default="", max_length=500)


class _SocketLike(Protocol):
    def sendall(self, data: bytes) -> None: ...
    def recv(self, size: int) -> bytes: ...
    def close(self) -> None: ...


class MalwareScanner(Protocol):
    def scan(self, content: bytes, *, filename: str | None = None) -> ScanResult: ...


class NoopScanner:
    """No scanner configured: store the file, and say it was not scanned."""

    def scan(self, content: bytes, *, filename: str | None = None) -> ScanResult:
        return ScanResult(
            outcome=ScanOutcome.DISABLED,
            scanner="none",
            detail="no malware scanner configured; the file was not scanned",
        )


class ClamAvScanner:
    """ClamAV over its INSTREAM protocol (TCP, no shell, bounded time)."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 3310,
        timeout: float = 5.0,
        connect: Callable[[tuple[str, int], float], _SocketLike] | None = None,
    ) -> None:
        if not host:
            raise ValueError("a ClamAV host is required")
        if not 0 < port < 65536:
            raise ValueError("a ClamAV port must be between 1 and 65535")
        self._host = host
        self._port = port
        self._timeout = timeout
        self._connect = connect or (
            lambda address, timeout: socket.create_connection(address, timeout=timeout)
        )

    def scan(self, content: bytes, *, filename: str | None = None) -> ScanResult:
        try:
            return self._scan(content)
        except (OSError, TimeoutError, ValueError) as exc:
            return ScanResult(
                outcome=ScanOutcome.UNAVAILABLE,
                scanner="clamav",
                detail=f"{type(exc).__name__}: the scanner did not answer",
            )

    def _scan(self, content: bytes) -> ScanResult:
        connection = self._connect((self._host, self._port), self._timeout)
        try:
            connection.sendall(b"zINSTREAM\0")
            for start in range(0, len(content), CHUNK_SIZE):
                chunk = content[start : start + CHUNK_SIZE]
                connection.sendall(struct.pack("!I", len(chunk)) + chunk)
            connection.sendall(struct.pack("!I", 0))
            response = bytearray()
            while b"\0" not in response and len(response) < 4096:
                data = connection.recv(1024)
                if not data:
                    break
                response.extend(data)
        finally:
            connection.close()

        text = bytes(response).split(b"\0", 1)[0].decode(errors="replace").strip()
        if text.endswith("stream: OK"):
            return ScanResult(outcome=ScanOutcome.CLEAN, scanner="clamav", detail="stream: OK")
        if "FOUND" in text:
            signature = text.removeprefix("stream: ").removesuffix(" FOUND")
            return ScanResult(
                outcome=ScanOutcome.INFECTED, scanner="clamav", detail=signature[:200]
            )
        return ScanResult(
            outcome=ScanOutcome.UNAVAILABLE,
            scanner="clamav",
            detail=f"unexpected scanner answer: {text[:100] or 'empty'}",
        )


def build_scanner(settings: object) -> MalwareScanner:
    """The configured scanner: ClamAV when a host is set, otherwise the honest no-op."""
    host = getattr(settings, "clamav_host", "")
    if not host:
        return NoopScanner()
    return ClamAvScanner(
        host=str(host),
        port=int(getattr(settings, "clamav_port", 3310)),
        timeout=float(getattr(settings, "clamav_timeout", 5.0)),
    )
