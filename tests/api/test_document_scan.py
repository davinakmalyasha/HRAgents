"""The upload route honours the scanner: off stores, unavailable refuses."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from hr_agents.config import Settings
from hr_agents.main import create_app


def upload(client: TestClient) -> Any:
    return client.post(
        "/v1/documents",
        files={"file": ("cv.txt", b"a candidate's cv", "text/plain")},
        data={"kind": "cv"},
    )


def test_without_a_scanner_the_upload_is_stored() -> None:
    with TestClient(create_app()) as client:
        response = upload(client)

    assert response.status_code == 201, response.text


def test_a_configured_but_unreachable_scanner_refuses_the_upload() -> None:
    settings = Settings(clamav_host="127.0.0.1", clamav_port=1, clamav_timeout=0.2)

    with TestClient(create_app(settings)) as client:
        response = upload(client)

    assert response.status_code == 503
    assert "not stored" in response.json()["detail"]
