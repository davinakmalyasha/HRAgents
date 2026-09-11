from fastapi.testclient import TestClient

from hr_agents import __version__
from hr_agents.config import get_settings
from hr_agents.main import app


def test_healthz() -> None:
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["environment"] == get_settings().environment


def test_openapi_schema_available() -> None:
    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"].endswith("API")
