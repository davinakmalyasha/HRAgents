"""Encryption for operator-entered provider configuration.

Provider configs contain API keys. They are stored encrypted rather than in a
plain JSON column, so a database backup, a replica, or a support dump does not
hand over every credential the operator ever entered.

The key is operator-supplied (`HRAGENTS_SETTINGS_ENCRYPTION_KEY`) and never
shipped. Comma-separated keys are accepted: the first encrypts, the rest decrypt,
which is what makes rotation possible without a downtime migration.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol


class SealerError(RuntimeError):
    """The ciphertext is unreadable: wrong key, or the value was tampered with."""


class Sealer(Protocol):
    def seal(self, payload: dict[str, Any]) -> str: ...

    def open(self, token: str) -> dict[str, Any]: ...


class FernetSealer:
    """AES-128-CBC + HMAC via `cryptography.fernet`, with a rotation list."""

    def __init__(self, keys: str | Sequence[str]) -> None:
        from cryptography.fernet import Fernet, MultiFernet

        parsed = [item.strip() for item in ([keys] if isinstance(keys, str) else keys)]
        parsed = [item for item in parsed if item]
        if not parsed:
            raise SealerError("at least one encryption key is required")
        try:
            self._fernet = MultiFernet([Fernet(key.encode()) for key in parsed])
        except Exception as exc:
            raise SealerError(
                "the encryption key is not a valid Fernet key (32 url-safe base64 bytes)"
            ) from exc

    def seal(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return self._fernet.encrypt(raw).decode()

    def open(self, token: str) -> dict[str, Any]:
        from cryptography.fernet import InvalidToken

        try:
            raw = self._fernet.decrypt(token.encode())
        except (InvalidToken, ValueError) as exc:
            raise SealerError("stored provider configuration cannot be decrypted") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SealerError("stored provider configuration is not valid JSON") from exc
        if not isinstance(value, dict):
            raise SealerError("stored provider configuration must be a JSON object")
        return value
