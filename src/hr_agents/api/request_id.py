"""Correlation ids: every request carries one, and every log line inherits it.

An operator looking at a failed screen needs to find the same moment in the
logs. Without an id the only join key is a timestamp, and a timestamp is a
guess. The id is generated here, bound into the logging context so every line
emitted while the request is in flight carries it, and echoed back so the
caller can quote it.
"""

from __future__ import annotations

from uuid import uuid4

import structlog.contextvars
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
MAX_REQUEST_ID_LENGTH = 64


def clean_request_id(candidate: str | None) -> str:
    """A printable, bounded id.

    A caller may propose one -- a gateway that already numbered the request --
    but it may not inject anything into the logs or the response headers, so
    the characters that could do that are dropped rather than escaped.
    """
    if candidate is None:
        return uuid4().hex
    cleaned = "".join(char for char in candidate.strip() if char.isalnum() or char in "-_.:")[
        :MAX_REQUEST_ID_LENGTH
    ]
    return cleaned or uuid4().hex


class RequestIdMiddleware:
    """Assign the request id, bind it to the log context, and echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = clean_request_id(Headers(scope=scope).get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_id)
        finally:
            structlog.contextvars.unbind_contextvars("request_id")
