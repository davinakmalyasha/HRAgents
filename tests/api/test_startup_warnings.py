"""Startup warnings: a production instance with no credential says so."""

from __future__ import annotations

import pytest
from structlog.testing import CapturingLogger

from hr_agents import main as main_module
from hr_agents.config import Settings
from hr_agents.main import create_app


def _events(logger: CapturingLogger) -> list[str]:
    return [str(call.args[0]) for call in logger.calls if call.args]


def test_a_production_instance_without_credentials_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(main_module, "logger", logger)

    create_app(Settings(environment="production", api_keys=[], api_principals=[]))

    assert "auth.disabled" in _events(logger)


def test_a_production_instance_with_a_key_is_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(main_module, "logger", logger)

    create_app(Settings(environment="production", api_keys=["a-key"]))

    assert "auth.disabled" not in _events(logger)


def test_local_development_never_nags(monkeypatch: pytest.MonkeyPatch) -> None:
    """The zero-config local install is a supported mode, not a misconfiguration."""
    logger = CapturingLogger()
    monkeypatch.setattr(main_module, "logger", logger)

    create_app(Settings(environment="local", api_keys=[], api_principals=[]))

    assert "auth.disabled" not in _events(logger)
