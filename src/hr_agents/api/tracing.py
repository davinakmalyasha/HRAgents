"""Optional OpenTelemetry tracing.

Off by default: an install with no collector pays for a no-op tracer and
nothing else. With `HRAGENTS_OTEL_ENDPOINT` set, FastAPI requests, outbound
HTTP calls and the two manual spans that matter (the worker's evaluation and
the extraction agent) are exported over OTLP/HTTP.

The provider is process-wide and built once. `create_app` is called by both the
API and the worker, so a second call instruments the new app with the existing
provider rather than fighting the SDK's one-time global.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import FastAPI
    from opentelemetry.sdk.trace import TracerProvider

    from hr_agents.config import Settings

_PROVIDER: TracerProvider | None = None


def traces_endpoint(raw: str) -> str:
    """The OTLP/HTTP traces URL, accepting a base or an already-suffixed endpoint."""
    trimmed = raw.strip().rstrip("/")
    return trimmed if trimmed.endswith("/v1/traces") else f"{trimmed}/v1/traces"


def configure_tracing(settings: Settings, *, app: FastAPI | None = None) -> Any:
    """Configure tracing when an endpoint is set; return the provider or None.

    ``excluded_urls`` keeps the probes and the scrape out of the trace set: they
    are the traffic that must stay cheap, and a health check is not a story.
    """
    global _PROVIDER
    if not settings.otel_endpoint:
        return None

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if _PROVIDER is None:
        provider = TracerProvider(
            resource=Resource.create({"service.name": settings.otel_service_name})
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint(settings.otel_endpoint)))
        )
        trace.set_tracer_provider(provider)
        _PROVIDER = provider

    if app is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_PROVIDER,
            excluded_urls="healthz,readyz,metrics,openapi.json,docs,redoc",
        )
    HTTPXClientInstrumentor().instrument(tracer_provider=_PROVIDER)
    return _PROVIDER
