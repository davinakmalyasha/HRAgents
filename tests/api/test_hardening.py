"""API hardening: security headers, body ceiling, rate limiting, readiness."""

from __future__ import annotations

from collections.abc import Iterator
from typing import cast

import pytest
from fastapi import FastAPI, Request
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


@pytest.fixture
def started_client() -> Iterator[TestClient]:
    """A client whose application lifespan has run.

    Readiness is only meaningful once startup has resolved the agents, the queue,
    and the chat â€” the plain ``client`` fixture deliberately skips the lifespan so
    the middleware tests stay independent of it.
    """
    with TestClient(create_app()) as started:
        yield started


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


def test_chunked_body_without_content_length_is_still_capped() -> None:
    """A chunked upload declares no length, so the header check cannot see it.

    The ceiling used to be a ``Content-Length`` comparison only. A client that
    sent ``Transfer-Encoding: chunked`` therefore had no bound at all on how much
    it could push: the header was absent, so nothing refused it and the body was
    buffered in full. The bytes are now counted as they stream.
    """

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)

    arrived: list[int] = []

    @app.post("/sink")
    async def sink(request: Request) -> dict[str, int]:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
        arrived.append(size)
        return {"length": size}

    response = TestClient(app).post(
        "/sink",
        content=iter([b"x" * 32, b"x" * 32, b"x" * 512]),
        headers={"transfer-encoding": "chunked"},
    )

    assert response.status_code == 413
    assert "exceeds 64 bytes" in response.json()["title"]
    # The upload was cut off rather than drained: the handler never saw the
    # 512-byte tail.
    assert sum(arrived) <= 64


def test_chunked_body_under_the_ceiling_is_delivered_whole() -> None:
    """The counter must not truncate a legitimate chunked upload."""

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)

    @app.post("/sink")
    async def sink(request: Request) -> dict[str, int]:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
        return {"length": size}

    response = TestClient(app).post(
        "/sink",
        content=iter([b"x" * 16, b"x" * 16]),
        headers={"transfer-encoding": "chunked"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"length": 32}


def test_rate_limit_key_ignores_the_api_key_header() -> None:
    """A caller must not be able to mint a fresh bucket per request.

    The bucket key used to fall back to the ``X-API-Key`` header when no
    principal was resolved. That header is entirely under the caller's control,
    so varying it gave every request its own allowance and the limiter protected
    nothing -- an unauthenticated flood, one bucket at a time.
    """
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    app = FastAPI()
    limiter = RateLimiter(limit=1, window_seconds=60.0)
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/ping")
    def ping() -> PlainTextResponse:
        return PlainTextResponse("pong")

    test_client = TestClient(app)
    first = test_client.get("/ping", headers={"x-api-key": "one"})
    second = test_client.get("/ping", headers={"x-api-key": "two"})

    assert first.status_code == 200
    assert second.status_code == 429


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


def test_readiness_reports_each_dependency(started_client: TestClient) -> None:
    report = readiness_report(cast(FastAPI, started_client.app))

    # Queue and skills are checked because they decide whether the product
    # *works*, not whether it starts: without a queue, submissions are accepted
    # and never evaluated; without skills, every agent runs with no runbook.
    assert report["status"] == "ok"
    assert set(report["checks"]) == {
        "database",
        "messaging",
        "audit",
        "queue",
        "skills",
    }
    assert report["checks"]["database"]["detail"] == "in-memory store"


def test_readiness_is_degraded_without_a_queue_backend() -> None:
    """The exact failure that made the product inert: no worker, no evaluation."""
    app = create_app()
    app.state.queue = None

    report = readiness_report(app)

    assert report["status"] == "degraded"
    assert report["checks"]["queue"]["status"] == "unavailable"
    assert "not evaluated" in report["checks"]["queue"]["detail"]


def test_readiness_is_degraded_without_the_skills_library() -> None:
    app = create_app()
    app.state.agents = None
    app.state.skills_error = "skills root /app/skills does not exist"

    report = readiness_report(app)

    assert report["status"] == "degraded"
    assert report["checks"]["skills"]["status"] == "unavailable"
    assert "/app/skills" in report["checks"]["skills"]["detail"]


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


def test_readyz_endpoint_reflects_the_report(started_client: TestClient) -> None:
    response = started_client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
