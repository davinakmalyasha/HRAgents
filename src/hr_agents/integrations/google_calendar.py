"""Google Calendar free/busy — a live adapter, not a config placeholder.

The calendar provider already declared the shape (``client_id``,
``client_secret``, ``refresh_token``, ``calendar_id``); this is the half that
actually talks to Google. It refreshes a short-lived access token from the
long-lived refresh token (Google's installed-app flow), caches it until it
expires, and asks the free/busy endpoint which intervals are already taken.

What it deliberately does **not** do: invent an interviewer directory. The
scheduler keys availability by an interviewer UUID and a Google calendar is
named by a calendar id; mapping one to the other is an operator decision, and a
wrong mapping would silently read the wrong person's calendar. The adapter is
what a directory would call, and ``scripts/check_calendar.py`` is the operator's
probe until that directory exists.

Busy windows are returned as ``TimeSlot`` intervals (UTC) so the scheduling
service can subtract them from an interviewer's working window without a second
interval type.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import httpx

from hr_agents.integrations.google_oauth import GoogleOAuthError, RefreshTokenOAuth
from hr_agents.logging import get_logger
from hr_agents.models import TimeSlot
from hr_agents.providers.calendar import GoogleCalendarConfig

logger = get_logger(__name__)

GOOGLE_CALENDAR_PROVIDER_ID = "calendar.google"


class GoogleCalendarError(RuntimeError):
    """The calendar did not answer with free/busy data."""


class GoogleCalendarBusy:
    """Refresh-token OAuth + free/busy lookup for one calendar."""

    def __init__(
        self,
        config: GoogleCalendarConfig,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._client = client or httpx.Client(timeout=30.0)
        self._oauth = RefreshTokenOAuth(
            client_id=config.client_id,
            client_secret=config.client_secret.get_secret_value(),
            refresh_token=config.refresh_token.get_secret_value(),
            token_url=config.token_url,
            client=self._client,
            clock=clock,
            provider="google calendar",
        )

    @property
    def provider_id(self) -> str:
        return GOOGLE_CALENDAR_PROVIDER_ID

    def busy(
        self, *, start: datetime, end: datetime, calendar_id: str | None = None
    ) -> list[TimeSlot]:
        """Intervals already booked in this calendar between ``start`` and ``end``.

        ``calendar_id`` overrides the configured one so one adapter can serve an
        interviewer directory; each call still names exactly one calendar.
        """
        if end <= start:
            raise GoogleCalendarError("free/busy end must be after start")
        target = (calendar_id or self._config.calendar_id).strip()
        if not target:
            raise GoogleCalendarError("a calendar id is required")
        # Validate before touching the network: a naive bound is a caller bug, and
        # a 401 from a token request would hide it behind a credential error.
        time_min = _rfc3339(start)
        time_max = _rfc3339(end)
        try:
            token = self._oauth.token()
        except GoogleOAuthError as exc:
            raise GoogleCalendarError(str(exc)) from exc
        url = f"{self._config.base_url.rstrip('/')}/calendar/v3/freeBusy"
        try:
            response = self._client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "items": [{"id": target}],
                },
            )
        except httpx.HTTPError as exc:
            raise GoogleCalendarError(
                f"{type(exc).__name__}: Google Calendar did not answer"
            ) from exc
        if response.status_code >= 400:
            raise GoogleCalendarError(_error_detail(response))
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleCalendarError("free/busy response was not JSON") from exc
        calendars = payload.get("calendars")
        entry = calendars.get(target) if isinstance(calendars, dict) else None
        if not isinstance(entry, dict):
            raise GoogleCalendarError(f"free/busy response has no entry for {target!r}")
        errors = entry.get("errors")
        if isinstance(errors, list) and errors:
            reason = str(errors[0].get("reason") or errors[0]) if errors else "unknown"
            raise GoogleCalendarError(f"free/busy refused the calendar: {reason}")
        busy = entry.get("busy")
        if not isinstance(busy, list):
            raise GoogleCalendarError("free/busy response has no busy list")
        slots: list[TimeSlot] = []
        for item in busy:
            try:
                window = TimeSlot(
                    start_utc=datetime.fromisoformat(str(item["start"])),
                    end_utc=datetime.fromisoformat(str(item["end"])),
                )
            except KeyError, TypeError, ValueError:
                # A malformed interval is not a busy window; dropping it silently
                # would hide a real booking, so the whole response is refused.
                raise GoogleCalendarError("free/busy returned a malformed interval") from None
            slots.append(window)
        return sorted(slots, key=lambda slot: slot.start_utc)


def _rfc3339(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise GoogleCalendarError("free/busy bounds must be timezone-aware")
    return moment.isoformat().replace("+00:00", "Z")


def _error_detail(response: httpx.Response) -> str:
    """Google's error message, bounded; the token and URL never appear in it."""
    try:
        payload: Any = response.json()
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            status = error.get("status")
        else:
            message = str(error or "")
            status = None
    except ValueError:
        message = response.text[:200]
        status = None
    detail = f"google calendar http {response.status_code}"
    if status:
        detail += f" ({status})"
    if message:
        detail += f": {message}"
    return detail[:500]


def build_google_calendar(config: GoogleCalendarConfig) -> GoogleCalendarBusy:
    return GoogleCalendarBusy(config)
