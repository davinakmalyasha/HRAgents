"""Static checks for the self-host packaging.

Docker is not available in every environment (and CI does not need it), so the
compose file, the Dockerfile, and the commands they reference are validated
here: a broken service command or a missing path only surfaces at deploy time
otherwise.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
DOCKERFILE_PATH = REPO_ROOT / "Dockerfile"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_compose_declares_the_whole_stack(compose: dict) -> None:
    services = compose["services"]

    assert {
        "postgres",
        "redis",
        "minio",
        "mailpit",
        "migrate",
        "api",
        "scheduler",
        "messaging",
    } <= set(services)
    for name in ("pgdata", "redisdata", "miniodata"):
        assert name in compose["volumes"]


def test_long_running_services_have_a_restart_policy(compose: dict) -> None:
    for name in ("api", "scheduler", "messaging", "postgres", "redis", "minio"):
        # The app services inherit the policy through the shared anchor.
        service = {**compose["services"]["api"], **compose["services"][name]}
        assert service["restart"] == "unless-stopped", name


def test_migrations_run_before_the_api_serves(compose: dict) -> None:
    api = compose["services"]["api"]
    migrations = api["depends_on"]["migrate"]

    assert migrations["condition"] == "service_completed_successfully"
    assert compose["services"]["migrate"]["command"] == ["alembic", "upgrade", "head"]


def test_the_app_uses_postgres_and_the_redis_queue(compose: dict) -> None:
    env = compose["services"]["api"]["environment"]

    assert env["HRAGENTS_STORE_BACKEND"] == "postgres"
    assert env["HRAGENTS_PROVIDER_QUEUE"] == "queue.redis"
    assert "postgres:5432" in env["HRAGENTS_DATABASE_URL"]


def test_scheduled_jobs_run_in_the_compose_scheduler(compose: dict) -> None:
    command = " ".join(compose["services"]["scheduler"]["command"])

    assert "scripts/run_scheduler.py" in command
    assert "--purge" in command
    assert "while true" in command


def test_messaging_runs_in_the_compose_messaging_service(compose: dict) -> None:
    command = " ".join(compose["services"]["messaging"]["command"])

    assert "scripts/run_messaging.py" in command
    assert "while true" in command


def test_compose_never_enables_live_email_by_default(compose: dict) -> None:
    # Mailpit is the local mail server; nothing must leave the machine unless an
    # operator explicitly points the transport at a real provider.
    assert compose["services"]["messaging"]["environment"]["HRAGENTS_MESSAGING_SANDBOX"] == "false"
    assert compose["services"]["messaging"]["environment"]["HRAGENTS_SMTP_HOST"] == "mailpit"


def test_every_script_the_image_runs_exists() -> None:
    for script in ("run_scheduler.py", "run_messaging.py", "verify_audit.py", "backup.py"):
        assert (REPO_ROOT / "scripts" / script).is_file(), script


def test_dockerfile_installs_the_locked_dependencies_and_runs_as_non_root() -> None:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "uv sync --locked" in text
    assert re.search(r"^USER hragents$", text, flags=re.MULTILINE)
    assert "HRAGENTS_WEB_DIST=/app/web/dist" in text
    assert "/healthz" in text


def test_dockerfile_copies_everything_the_api_imports() -> None:
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")

    for path in (
        "src/",
        "migrations/",
        "scripts/",
        "alembic.ini",
        "pyproject.toml uv.lock README.md",
    ):
        assert f"COPY {path}" in text, path


def test_dockerignore_excludes_secrets_and_heavy_directories() -> None:
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")

    assert ".env" in text.splitlines()
    assert "**/node_modules" in text.splitlines()
    assert "**/__pycache__" in text.splitlines()


def test_the_dashboard_assets_are_not_excluded_from_the_image() -> None:
    lines = DOCKERIGNORE_PATH.read_text(encoding="utf-8").splitlines()

    # The build stage produces web/dist; the ignore must not ship it twice.
    assert "web/dist" not in lines
    assert "web" not in lines
