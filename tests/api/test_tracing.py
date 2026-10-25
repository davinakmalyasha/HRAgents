"""Tracing is optional: no endpoint, no provider; a base URL is normalized."""

from __future__ import annotations

from typing import Any

from opentelemetry import trace

from hr_agents.api.tracing import configure_tracing, traces_endpoint
from hr_agents.config import Settings


def test_no_endpoint_means_no_provider() -> None:
    assert configure_tracing(Settings(otel_endpoint="")) is None


def test_the_endpoint_accepts_a_base_or_a_full_traces_url() -> None:
    assert traces_endpoint("http://collector:4318") == "http://collector:4318/v1/traces"
    assert traces_endpoint("http://collector:4318/") == "http://collector:4318/v1/traces"
    assert traces_endpoint("http://collector:4318/v1/traces") == "http://collector:4318/v1/traces"


def test_an_endpoint_installs_the_process_provider() -> None:
    provider: Any = configure_tracing(
        Settings(otel_endpoint="http://localhost:4318", otel_service_name="hragents-test")
    )

    assert provider is not None
    assert trace.get_tracer_provider() is provider
    # The global provider outlives this test; stop its exporter so later
    # spans in the suite are dropped instead of timing out against a
    # collector that is not running.
    getattr(provider, "shutdown", lambda: None)()
