"""Google OAuth refresh-token flow, shared by the live Google adapters.

One place for the grant, the cache and the early refresh: Calendar and Gmail
both need a short-lived access token from an operator's long-lived refresh
token, and two copies of that logic would drift on the expiry margin — the part
that decides whether a request carries a token that dies mid-flight.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from hr_agents.logging import get_logger

logger = get_logger(__name__)

TOKEN_SAFETY_SECONDS = 60
"""Refresh a little early: a token that expires mid-request is a 401 the operator
reads as a configuration fault."""


class GoogleOAuthError(RuntimeError):
    """The token endpoint refused or did not answer."""


@dataclass
class RefreshTokenOAuth:
    """Mint and cache access tokens from a refresh token."""

    client_id: str
    client_secret: str
    refresh_token: str
    token_url: str
    client: httpx.Client
    clock: Callable[[], float] = time.time
    provider: str = "google"
    _token: str | None = None
    _expires_at: float = 0.0

    def token(self) -> str:
        if self._token is not None and self.clock() < self._expires_at:
            return self._token
        try:
            response = self.client.post(
                self.token_url,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleOAuthError(
                f"{type(exc).__name__}: the token endpoint did not answer"
            ) from exc
        if response.status_code >= 400:
            raise GoogleOAuthError(_error_detail(response, provider=self.provider))
        try:
            payload = response.json()
            token = str(payload["access_token"])
        except ValueError, KeyError, TypeError:
            raise GoogleOAuthError("the token endpoint returned no access token") from None
        try:
            lifetime = float(payload.get("expires_in", 3600))
        except TypeError, ValueError:
            lifetime = 3600.0
        self._token = token
        self._expires_at = self.clock() + max(lifetime - TOKEN_SAFETY_SECONDS, 0.0)
        return token


def _error_detail(response: httpx.Response, *, provider: str) -> str:
    """The endpoint's own error, bounded; credentials never appear in it."""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = str(payload.get("error") or "")
            description = str(payload.get("error_description") or "")
            message = f"{error}: {description}" if description else error
        else:
            message = ""
    except ValueError:
        message = response.text[:200]
    detail = f"{provider} token http {response.status_code}"
    if message:
        detail += f": {message}"
    return detail[:500]
