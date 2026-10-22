"""Correlation ids: generated, echoed, and bound to the log context."""

from __future__ import annotations

import re

import structlog
import structlog.contextvars
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from hr_agents.api.request_id import REQUEST_ID_HEADER, RequestIdMiddleware, clean_request_id
from hr_agents.main import create_app

HEX_ID = re.compile(r"^[0-9a-f]{32}$")


def test_every_response_carries_a_request_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert HEX_ID.match(request_id), request_id


def test_a_caller_may_propose_the_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={REQUEST_ID_HEADER: "edge-42"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-42"


def test_a_hostile_id_cannot_inject_anything() -> None:
    """A header is attacker-controlled, so it may not carry newlines or length."""
    cleaned = clean_request_id("edge-42\r\nX-Evil: 1")

    assert cleaned == "edge-42X-Evil:1"
    assert "\n" not in cleaned
    assert len(clean_request_id("a" * 500)) == 64


def test_the_id_reaches_the_logs() -> None:
    """A log line emitted while the request is in flight carries the id."""
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        structlog.get_logger("test").info("ping.seen")
        return {"ok": "true"}

    with (
        TestClient(app) as client,
        capture_logs(processors=[structlog.contextvars.merge_contextvars]) as events,
    ):
        response = client.get("/ping", headers={REQUEST_ID_HEADER: "edge-7"})

    assert response.headers[REQUEST_ID_HEADER] == "edge-7"
    assert events[0]["request_id"] == "edge-7"
