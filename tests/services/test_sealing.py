"""Sealing provider configuration: round-trip, tamper detection, rotation."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from hr_agents.services.sealing import FernetSealer, SealerError


def key() -> str:
    return Fernet.generate_key().decode()


def test_a_config_round_trips_and_the_ciphertext_does_not_contain_it() -> None:
    sealer = FernetSealer(key())

    sealed = sealer.seal({"api_key": "sk-live-secret", "region": "id"})

    assert "sk-live-secret" not in sealed
    assert sealer.open(sealed) == {"api_key": "sk-live-secret", "region": "id"}


def test_a_tampered_token_is_refused() -> None:
    sealer = FernetSealer(key())
    sealed = sealer.seal({"api_key": "x"})

    with pytest.raises(SealerError, match="cannot be decrypted"):
        sealer.open(sealed[:-2] + "AA")


def test_another_key_cannot_open_it() -> None:
    sealer = FernetSealer(key())
    sealed = sealer.seal({"api_key": "x"})

    with pytest.raises(SealerError):
        FernetSealer(key()).open(sealed)


def test_rotation_reads_old_tokens_and_writes_with_the_new_key() -> None:
    old = key()
    new = key()
    old_token = FernetSealer(old).seal({"api_key": "x"})
    rotating = FernetSealer([new, old])

    assert rotating.open(old_token) == {"api_key": "x"}

    with pytest.raises(SealerError):
        FernetSealer(old).open(rotating.seal({"api_key": "y"}))


def test_an_invalid_or_empty_key_is_a_startup_refusal() -> None:
    with pytest.raises(SealerError, match="at least one"):
        FernetSealer("")
    with pytest.raises(SealerError, match="valid Fernet key"):
        FernetSealer("not-a-key")
