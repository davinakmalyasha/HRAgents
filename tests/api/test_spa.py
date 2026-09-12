"""Built dashboard serving: ``/app`` assets with SPA fallback."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hr_agents.main import create_app

INDEX_HTML = "<!doctype html><div id=root>hragents</div>"


@pytest.fixture
def web_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setenv("HRAGENTS_WEB_DIST", str(tmp_path))
    return tmp_path


def test_dashboard_index_is_served(web_dist: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/app")
    assert response.status_code == 200
    assert "hragents" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_client_routes_fall_back_to_index(web_dist: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/app/hiring/candidates/123")
    assert response.status_code == 200
    assert "hragents" in response.text


def test_root_static_files_are_served_with_their_type(web_dist: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/app/favicon.svg")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_hashed_assets_mount_is_served(web_dist: Path) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/app/assets/app.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_path_traversal_falls_back_to_index(
    web_dist: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with TestClient(create_app()) as client:
        response = client.get("/app/..%2Fpyproject.toml")
    assert response.status_code == 200
    assert "hragents" in response.text


def test_app_route_is_absent_without_a_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HRAGENTS_WEB_DIST", str(tmp_path / "missing"))
    with TestClient(create_app()) as client:
        response = client.get("/app")
    assert response.status_code == 404
