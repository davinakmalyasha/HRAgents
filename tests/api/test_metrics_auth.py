"""The Prometheus scrape surface: public by default, bearer-gated when configured."""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import Settings
from hr_agents.main import create_app

TOKEN = "scrape-token-1"


def test_metrics_is_public_when_no_token_is_configured() -> None:
    with TestClient(create_app(Settings(metrics_token=None))) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_a_configured_token_is_required() -> None:
    app = create_app(Settings(metrics_token=SecretStr(TOKEN)))

    with TestClient(app) as client:
        missing = client.get("/metrics")
        wrong = client.get("/metrics", headers={"Authorization": "Bearer nope"})
        correct = client.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert correct.status_code == 200
    # The refusal is a problem document like every other error, so a scraper
    # logging it gets a code rather than prose to parse.
    assert missing.json()["code"] == "auth_invalid"
    assert TOKEN not in missing.text


def test_a_bare_authorization_header_is_not_mistaken_for_a_token() -> None:
    with TestClient(create_app(Settings(metrics_token=SecretStr(TOKEN)))) as client:
        response = client.get("/metrics", headers={"Authorization": TOKEN})

    assert response.status_code == 401
