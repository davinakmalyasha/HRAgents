"""API hardening: security headers, body ceiling, rate limiting, readiness."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hr_agents.api.hardening import (
    BASE_SECURITY_HEADERS,
    DASHBOARD_CSP,
    BodySizeLimitMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    readiness_report,
)
from hr_agents.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


# --- headers -----------------------------------------------------------------


def test_every_response_carries_the_hardening_headers(client: TestClient) -> None:
    response = client.get("/healthz")

    for name, value in BASE_SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert response.headers["content-security-policy"] == "default-src 'none'"


def test_dashboard_gets_the_spa_content_security_policy(client: TestClient) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient as Client

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/app")
    def dashboard() -> PlainTextResponse:
        return PlainTextResponse("dashboard")

    @app.get("/api")
    def api() -> PlainTextResponse:
        return PlainTextResponse("api")

    test_client = Client(app)
    assert test_client.get("/app").headers["content-security-policy"] == DASHBOARD_CSP
    assert test_client.get("/api").headers["content-security-policy"] == "default-src 'none'"


def test_production_enables_hsts(client: TestClient) -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse
    from fastapi.testclient import TestClient as Client

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, hsts=True)

    @app.get("/x")
    def endpoint() -> PlainTextResponse:
        return PlainTextResponse("ok")

    response = Client(app).get("/x")
    assert "max-age=31536000" in response.headers["strict-transport-security"]


# --- body ceiling -------------------------------------------------------------


def test_oversized_body_is_refused_before_it_is_read() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)

    @app.post("/echo")
    def echo(payload: dict[str, int]) -> dict[str, int]:
        return payload

    test_client = TestClient(app)
    response = test_client.post("/echo", json={"value": "x" * 512})

    assert response.status_code == 413
    assert "exceeds 64 bytes" in response.json()["title"]


def test_body_under_the_ceiling_passes() -> None:
    from fastapi import FastAPI

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=4096)

    @app.post("/echo")
    def echo(payload: dict[str, int]) -> dict[str, int]:
        return payload

    assert TestClient(app).post("/echo", json={"value": 1}).status_code == 200


# --- rate limiting ------------------------------------------------------------


def test_limiter_allows_a_burst_then_throttles() -> None:
    now = [1000.0]
    limiter = RateLimiter(limit=3, window_seconds=60.0, _now=lambda: now[0])

    assert [limiter.check("actor:hr")[0] for _ in range(4)] == [True, True, True, False]
    allowed, retry_after = limiter.check("actor:hr")
    assert allowed is False
    assert 0.0 < retry_after <= 60.0

    now[0] += 61.0
    assert limiter.check("actor:hr")[0] is True


def test_limiter_is_per_key() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60.0)

    assert limiter.check("actor:a")[0] is True
    assert limiter.check("actor:a")[0] is False
    assert limiter.check("actor:b")[0] is True


def test_rate_limited_request_returns_429_with_retry_after() -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(limit=2, window_seconds=60.0))

    @app.get("/ping")
    def ping() -> PlainTextResponse:
        return PlainTextResponse("pong")

    test_client = TestClient(app)
    assert test_client.get("/ping").status_code == 200
    assert test_client.get("/ping").status_code == 200
    throttled = test_client.get("/ping")

    assert throttled.status_code == 429
    assert int(throttled.headers["Retry-After"]) >= 1


def test_probes_are_exempt_from_rate_limiting() -> None:
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=RateLimiter(limit=1, window_seconds=60.0))

    @app.get("/readyz")
    def readyz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    test_client = TestClient(app)
    for _ in range(5):
        assert test_client.get("/readyz").status_code == 200


# --- readiness ----------------------------------------------------------------


def test_readiness_reports_each_dependency() -> None:
    app = create_app()

    report = readiness_report(app)

    assert report["status"] == "ok"
    assert set(report["checks"]) == {"database", "messaging", "audit"}
    assert report["checks"]["database"]["detail"] == "in-memory store"


def test_readiness_is_degraded_when_the_database_is_unreachable() -> None:
    class BrokenEngine:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def connect(self) -> object:
            raise OSError("connection refused")

    app = create_app()
    app.state.db_engine = BrokenEngine()

    report = readiness_report(app)

    assert report["status"] == "degraded"
    assert report["checks"]["database"] == {"status": "unavailable", "detail": "OSError"}


def test_readyz_endpoint_reflects_the_report(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
