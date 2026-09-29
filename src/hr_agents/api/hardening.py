"""API hardening middleware: security headers, body-size guard, rate limiting.

Defaults are deliberately conservative and configurable, because a self-hosted
deployment sits on a private network as often as on the open internet:

- security headers on every response (CSP only for the bundled dashboard),
- a request body ceiling enforced before the body is read,
- a token-bucket rate limit per principal (or client address) with ``Retry-After``,
- a CORS policy that is off unless origins are configured explicitly.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from hr_agents.api.metrics import record_http_request
from hr_agents.config import Settings, get_settings

DEFAULT_MAX_BODY_BYTES = 10 * 1024 * 1024
"""10 MiB: the same ceiling the document endpoint enforces per file."""

DEFAULT_RATE_LIMIT_PER_MINUTE = 300

BASE_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}

DASHBOARD_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


@dataclass
class RateLimiter:
    """In-process sliding-window limiter keyed by client.

    Single-process by design: it protects one instance from a runaway client and
    a credential-stuffing loop. A shared store belongs behind a provider when a
    deployment runs more than one API process.
    """

    limit: int = DEFAULT_RATE_LIMIT_PER_MINUTE
    window_seconds: float = 60.0
    max_tracked_keys: int = 10_000
    _hits: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _now: Callable[[], float] = time.monotonic

    def check(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)`` for one request."""
        now = self._now()
        window = self._hits[key]
        while window and now - window[0] >= self.window_seconds:
            window.popleft()
        if len(window) >= self.limit:
            return False, max(0.0, self.window_seconds - (now - window[0]))
        window.append(now)
        self._evict(now)
        return True, 0.0

    def _evict(self, now: float) -> None:
        """Bound the bucket table.

        Buckets are only trimmed on *reuse*, so a caller presenting a fresh
        client address on every request would otherwise grow this dict until the
        process died. Insertion order is preserved, so the oldest bucket is the
        least likely to be in active use.
        """
        if len(self._hits) <= self.max_tracked_keys:
            return
        for stale_key in list(self._hits)[: len(self._hits) - self.max_tracked_keys]:
            del self._hits[stale_key]

    def reset(self) -> None:
        self._hits.clear()


def client_key(request: Request) -> str:
    """Bucket by authenticated actor, then API key, then client address.

    ``X-Forwarded-For`` is honoured only when the operator declares a trusted
    proxy in front of the app. Trusting it unconditionally lets any caller mint
    a fresh rate-limit bucket per request simply by varying the header, which
    defeats the limit entirely on the unauthenticated path — the default in a
    fresh install.
    """
    actor = getattr(request.state, "actor_id", None)
    if isinstance(actor, str) and actor:
        return f"actor:{actor}"
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"key:{hash(api_key)}"
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"
    client = request.client
    return f"ip:{client.host if client else 'unknown'}"


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """Time every request into the metrics counters.

    Registered last so it is the innermost wrapper and measures application
    time rather than the other middlewares' overhead.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or "unmatched"
        record_http_request(route_path, response.status_code, elapsed)
        response.headers.setdefault("X-Response-Time-Ms", f"{elapsed * 1000:.1f}")
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds the hardening headers to every response."""

    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in BASE_SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        response.headers.setdefault(
            "Content-Security-Policy",
            DASHBOARD_CSP if request.url.path.startswith("/app") else "default-src 'none'",
        )
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse oversized bodies before they are buffered."""

    def __init__(self, app: ASGIApp, *, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            return JSONResponse(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                content={
                    "type": "about:blank",
                    "title": f"request body exceeds {self._max_bytes} bytes",
                    "status": status.HTTP_413_CONTENT_TOO_LARGE,
                    "instance": request.url.path,
                },
            )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket gate with a standard ``Retry-After`` response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter | None = None,
        limit: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        exempt_paths: Iterable[str] = ("/healthz", "/readyz"),
    ) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter(limit=limit)
        self._exempt = frozenset(exempt_paths)

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self._exempt:
            return await call_next(request)
        allowed, retry_after = self._limiter.check(client_key(request))
        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(int(retry_after) + 1)},
                content={
                    "type": "about:blank",
                    "title": "rate limit exceeded",
                    "status": status.HTTP_429_TOO_MANY_REQUESTS,
                    "instance": request.url.path,
                },
            )
        return await call_next(request)


def install_hardening(
    app: FastAPI,
    settings: Settings,
    *,
    limiter: RateLimiter | None = None,
) -> None:
    """Register the hardening middleware and the CORS policy."""
    if settings.api_cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.api_cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-API-Key"],
            max_age=600,
        )
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter or RateLimiter(limit=settings.api_rate_limit_per_minute),
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api_max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")
    app.add_middleware(RequestMetricsMiddleware)


def readiness_report(app: FastAPI) -> dict[str, Any]:
    """Check the dependencies the API cannot work without.

    ``ready`` is false when a configured dependency is unreachable; in local
    in-memory mode everything is trivially ready, which is the zero-config
    default this project ships with.
    """
    checks: dict[str, Any] = {}

    engine: Any = getattr(app.state, "db_engine", None)
    if engine is None:
        checks["database"] = {"status": "ok", "detail": "in-memory store"}
    else:
        try:
            with engine.connect() as connection:
                connection.exec_driver_sql("SELECT 1")
            checks["database"] = {"status": "ok", "detail": type(engine.dialect).__name__}
        except Exception as exc:  # readiness must report, never raise
            checks["database"] = {"status": "unavailable", "detail": type(exc).__name__}

    messaging: Any = getattr(app.state, "messaging", None)
    checks["messaging"] = {
        "status": "ok",
        "detail": "sandbox" if messaging is None or not messaging.live else messaging.provider_id,
    }

    audit: Any = getattr(app.state, "audit", None)
    checks["audit"] = {
        "status": "ok",
        "detail": type(audit).__name__ if audit is not None else "missing",
    }

    # The queue and the skills library decide whether the product *works*, not
    # just whether it starts. A missing queue means submitted applications are
    # accepted and never evaluated; a missing skills root means every agent runs
    # without its runbook. Both are degradations an operator must see.
    queue_backend: Any = getattr(app.state, "queue", None)
    checks["queue"] = {
        "status": "ok" if queue_backend is not None else "unavailable",
        "detail": type(queue_backend).__name__
        if queue_backend is not None
        else "no queue backend resolved; applications will be accepted but not evaluated",
    }

    agents: Any = getattr(app.state, "agents", None)
    if agents is None:
        skills_error = getattr(app.state, "skills_error", None) or "skills library not loaded"
        checks["skills"] = {"status": "unavailable", "detail": skills_error}
    else:
        checks["skills"] = {
            "status": "ok",
            "detail": f"{len(agents.agent_names)} agents, {len(agents.namespaces)} namespaces",
        }

    return {
        "status": "ok" if all(check["status"] == "ok" for check in checks.values()) else "degraded",
        "checks": checks,
    }
