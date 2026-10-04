# HRAgents self-host image.
#
# Two stages: the dashboard is built once with Node, then only the Python
# runtime and the built assets are copied into a slim image that runs as a
# non-root user. No dev dependencies, no source maps, no toolchain.

# --- stage 1: build the dashboard -------------------------------------------------
# Pinned to the same major that CI lints, typechecks, tests and builds with
# (`web/.nvmrc`, consumed by the `web` job's `node-version-file`). Building the
# shipped bundle on a different toolchain than the one under test means nothing
# ever validated the artifact that actually ships.
FROM node:26-bookworm-slim AS web

WORKDIR /build/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- stage 2: runtime ------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    HRAGENTS_WEB_DIST=/app/web/dist \
    HRAGENTS_SKILLS_ROOT=/app/skills

# libpq for psycopg, curl for the container healthcheck, postgresql-client for
# scripts/backup.py (pg_dump/psql/createdb/dropdb) which the backup runbook
# invokes from inside this image.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so code edits do not reinstall the world.
# LICENSE is here because pyproject declares `license-files = ["LICENSE"]`, and
# PEP 639 requires a build tool to error on a pattern that matches no file.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
# The skills library is agent instruction content, not code, but the agents
# cannot run without it: omitting it served a dashboard whose chat 503'd.
COPY skills/ ./skills/
COPY alembic.ini ./
RUN uv sync --locked --no-dev \
    && chmod +x scripts/*.py \
    && useradd --create-home --uid 10001 hragents \
    && chown -R hragents:hragents /app

COPY --from=web /build/web/dist ./web/dist
RUN chown -R hragents:hragents /app/web

USER hragents

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "hr_agents.main:app", "--host", "0.0.0.0", "--port", "8000"]
