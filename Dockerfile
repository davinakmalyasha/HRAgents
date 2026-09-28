# HRAgents self-host image.
#
# Two stages: the dashboard is built once with Node, then only the Python
# runtime and the built assets are copied into a slim image that runs as a
# non-root user. No dev dependencies, no source maps, no toolchain.

# --- stage 1: build the dashboard -------------------------------------------------
FROM node:22-bookworm-slim AS web

WORKDIR /build/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
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
    HRAGENTS_WEB_DIST=/app/web/dist

# libpq for psycopg, curl for the container healthcheck
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.14 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer first so code edits do not reinstall the world.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src/ ./src/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
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
