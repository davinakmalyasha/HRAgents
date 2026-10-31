"""API hardening middleware: security headers, body-size guard, rate limiting.

Defaults are deliberately conservative and configurable, because a self-hosted
deployment sits on a private network as often as on the open internet:

- security headers on every response (CSP only for the bundled dashboard),
- a request body ceiling enforced before the body is read,
- a token-bucket rate limit per principal (or client address) with ``Retry-After``,
  in memory for one process or in Redis when several share the limit,
- a CORS policy that is off unless origins are configured explicitly.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from hr_agents.api.auth import AuthenticationMiddleware
from hr_agents.api.metrics import record_http_request
from hr_agents.api.problem import PROBLEM_MEDIA_TYPE, ProblemCode, problem_uri
from hr_agents.api.request_id import RequestIdMiddleware
from hr_agents.config import Settings, get_settings
from hr_agents.logging import get_logger

logger = get_logger(__name__)

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
    _last_hit: dict[str, float] = field(default_factory=dict)
    _now: Callable[[], float] = time.monotonic

    def check(self, key: str) -> tuple[bool, float]:
        """Return ``(allowed, retry_after_seconds)`` for one request."""
        now = self._now()
        window = self._hits[key]
        while window and now - window[0] >= self.window_seconds:
            window.popleft()
        self._last_hit[key] = now
        if len(window) >= self.limit:
            return False, max(0.0, self.window_seconds - (now - window[0]))
        window.append(now)
        self._evict(now, key)
        return True, 0.0

    @property
    def tracked_keys(self) -> int:
        """How many client buckets are held. Bounded by ``max_tracked_keys``."""
        return len(self._hits)

    def _evict(self, now: float, keep: str) -> None:
        """Bound the bucket table without resetting anybody's window.

        Buckets are only trimmed on *reuse*, so a caller presenting a fresh
        client address on every request would otherwise grow this dict until the
        process died.

        The old policy dropped the oldest *inserted* buckets, which could be a
        busy principal's: their counter restarted and their limit stopped
        meaning anything, which is a way to make the limiter useless for
        everybody else. Buckets whose window has fully expired go first, then the
        least recently used -- and never the key being checked, or a throttled
        caller would clear its own bucket and start over.
        """
        if len(self._hits) <= self.max_tracked_keys:
            return
        for key, window in list(self._hits.items()):
            if key == keep:
                continue
            if not window or now - window[0] >= self.window_seconds:
                del self._hits[key]
                self._last_hit.pop(key, None)
        while len(self._hits) > self.max_tracked_keys:
            victim = min(
                (key for key in self._hits if key != keep),
                key=lambda key: self._last_hit.get(key, 0.0),
                default=None,
            )
            if victim is None:
                return
            del self._hits[victim]
            self._last_hit.pop(victim, None)

    def reset(self) -> None:
        self._hits.clear()
        self._last_hit.clear()


def client_key(request: Request) -> str:
    """Bucket by authenticated actor, falling back to the client address.

    The fallback is deliberately the address and nothing else. There was a
    middle case that bucketed by a hash of the presented API key, which looked
    safer than the address and was strictly worse: on a request that *failed*
    to authenticate, the key is attacker-controlled, so every guess minted a
    fresh bucket. Rotating ``X-API-Key`` turned the limiter off completely, and
    the limiter is the only thing standing between an attacker and online key
    guessing -- every one of those requests came back 401, so nothing downstream
    was stopping them.

    The same trap applies to ``X-Forwarded-For``, which is honoured only when the
    operator declares a trusted proxy in front of the app.
    """
    actor = getattr(request.state, "actor_id", None)
    if isinstance(actor, str) and actor:
        return f"actor:{actor}"
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


@dataclass
class _BodyCounter:
    """Per-request byte tally, readable by the error path."""

    limit: int
    received: int = 0
    exceeded: bool = False


class BodySizeLimitMiddleware:
    """Refuse oversized bodies while they stream in, not after.

    Checking the ``Content-Length`` header alone is advisory: a client sending
    ``Transfer-Encoding: chunked`` sends no ``Content-Length`` at all, so the
    body was accepted with no bound and buffered in full before anything looked
    at it. This wraps the ASGI ``receive`` channel and counts the bytes as they
    arrive, which is the only place a chunked upload can be stopped. A declared
    length is still checked first, so an oversized declared body is refused
    without reading a byte of it.
    """

    def __init__(self, app: ASGIApp, *, max_bytes: int = DEFAULT_MAX_BODY_BYTES) -> None:
        self._app = app
        self._max_bytes = max_bytes

    def _too_large(self, path: str) -> JSONResponse:
        # Built here rather than raised: this is pure ASGI middleware, below the router,
        # so there is no exception handler to run. It emits the same problem document the
        # handler does, including the media type -- previously this and the rate limiter
        # sent the same keys as `application/json`, so a client that branched on
        # `application/problem+json` silently treated an oversized upload as a success.
        code = ProblemCode.PAYLOAD_TOO_LARGE
        return JSONResponse(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            media_type=PROBLEM_MEDIA_TYPE,
            content={
                "type": problem_uri(code),
                "title": f"request body exceeds {self._max_bytes} bytes",
                "status": status.HTTP_413_CONTENT_TOO_LARGE,
                "detail": f"request body exceeds {self._max_bytes} bytes",
                "instance": path,
                "code": code.value,
            },
        )

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = self._too_large(scope.get("path", ""))
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self._max_bytes:
            await self._reject(scope, receive, send)
            return

        limit = self._max_bytes
        state = _BodyCounter(limit)

        async def counted_receive() -> Message:
            message = await receive()
            if message["type"] == "http.request":
                state.received += len(message.get("body", b""))
                if state.received > limit:
                    # Stop the upload rather than draining it: a hostile client
                    # would otherwise keep writing while we keep reading.
                    state.exceeded = True
                    message = {"type": "http.disconnect"}
            return message

        scope.setdefault("state", {})["body_counter"] = state
        try:
            await self._app(scope, counted_receive, send)
        except ClientDisconnect:
            if state.exceeded:
                await self._reject(scope, receive, send)
                return
            raise


class RateLimitStore(Protocol):
    """Where request counts live: this process, or a store every replica shares."""

    async def hit(self, key: str) -> tuple[bool, float]: ...


class InMemoryRateLimitStore:
    """The default: one process's sliding window, no external dependency."""

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def hit(self, key: str) -> tuple[bool, float]:
        return self._limiter.check(key)


_REDIS_KEY_PREFIX = "hragents:ratelimit:"
"""One sorted set per bucket; a shared prefix makes an operator's flush easy to target."""


class RedisRateLimitStore:
    """A shared sliding window, for a deployment running several API processes.

    A refusal is ``Retry-After`` seconds computed from the oldest hit still in
    the window, so a throttled client is told when it may retry rather than
    being handed a guess. If Redis is unreachable the limiter **fails open** and
    logs: the queue and the stores are down in that state anyway, and refusing
    every request would turn a dependency outage into an outage of the product.

    The window is a Redis transaction (WATCH → trim/count → MULTI add) rather
    than a Lua script, so it runs on any Redis and on ``fakeredis`` without the
    Lua extra. Under contention a write loses the watch and retries; after
    ``attempts`` losses the request is allowed rather than starved, which is the
    same fail-open posture as an unreachable store.
    """

    def __init__(
        self,
        client: Any,
        *,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
        attempts: int = 3,
    ) -> None:
        self._client = client
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts = attempts

    async def hit(self, key: str) -> tuple[bool, float]:
        from redis.exceptions import WatchError

        redis_key = f"{_REDIS_KEY_PREFIX}{key}"
        for _ in range(self._attempts):
            now = self._clock()
            try:
                async with self._client.pipeline() as pipe:
                    await pipe.watch(redis_key)
                    await pipe.zremrangebyscore(redis_key, 0, now - self._window_seconds)
                    count = int(await pipe.zcard(redis_key))
                    if count >= self._limit:
                        oldest = await pipe.zrange(redis_key, 0, 0, withscores=True)
                        await pipe.unwatch()
                        if not oldest:
                            return True, 0.0
                        retry_after = float(oldest[0][1]) + self._window_seconds - now
                        return False, max(0.0, retry_after)
                    pipe.multi()
                    pipe.zadd(redis_key, {f"{now}:{uuid4().hex}": now})
                    pipe.expire(redis_key, math.ceil(self._window_seconds))
                    await pipe.execute()
                    return True, 0.0
            except WatchError:
                continue
            except Exception:
                logger.error("rate_limit.store_unavailable", exc_info=True)
                return True, 0.0
        logger.warning("rate_limit.store_contended", key=key, attempts=self._attempts)
        return True, 0.0


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket gate with a standard ``Retry-After`` response."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter | None = None,
        store: RateLimitStore | None = None,
        limit: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        exempt_paths: Iterable[str] = ("/healthz", "/readyz"),
    ) -> None:
        super().__init__(app)
        self._limiter = limiter or RateLimiter(limit=limit)
        self._store = store or InMemoryRateLimitStore(self._limiter)
        self._exempt = frozenset(exempt_paths)

    @property
    def limiter(self) -> RateLimiter:
        return self._limiter

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in self._exempt:
            return await call_next(request)
        allowed, retry_after = await self._store.hit(client_key(request))
        if not allowed:
            # Same reasoning as `_too_large`: ASGI middleware, so the document is built
            # here. `rate_limited` is the one code the frontend had no translation for,
            # so a throttled user was told "something went wrong" and invited to retry
            # into the limit.
            code = ProblemCode.RATE_LIMITED
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type=PROBLEM_MEDIA_TYPE,
                headers={"Retry-After": str(int(retry_after) + 1)},
                content={
                    "type": problem_uri(code),
                    "title": "rate limit exceeded",
                    "status": status.HTTP_429_TOO_MANY_REQUESTS,
                    "detail": "too many requests; retry after the interval in Retry-After",
                    "instance": request.url.path,
                    "code": code.value,
                },
            )
        return await call_next(request)


def install_hardening(
    app: FastAPI,
    settings: Settings,
    *,
    limiter: RateLimiter | None = None,
    rate_limit_store: RateLimitStore | None = None,
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
    store = rate_limit_store
    if store is None and settings.rate_limit_backend == "redis":
        from redis.asyncio import Redis

        store = RedisRateLimitStore(
            Redis.from_url(settings.redis_url, decode_responses=True),
            limit=settings.api_rate_limit_per_minute,
        )
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter or RateLimiter(limit=settings.api_rate_limit_per_minute),
        store=store,
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.api_max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.environment == "production")
    app.add_middleware(RequestMetricsMiddleware)
    # Added last, so it is the outermost wrapper: Starlette applies user
    # middleware in reverse registration order. Authentication must run before
    # the rate limiter for the limiter's per-principal bucket to work at all --
    # `client_key` reads `request.state.actor_id`, which nothing else sets.
    app.add_middleware(AuthenticationMiddleware, settings=settings)
    # Outermost, so the id is bound before anything else runs and every log line
    # the request produces carries it.
    app.add_middleware(RequestIdMiddleware)


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
