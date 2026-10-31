"""Google Calendar free/busy: OAuth refresh, caching, and the exact request."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from pydantic import SecretStr

from hr_agents.integrations.google_calendar import (
    GoogleCalendarBusy,
    GoogleCalendarError,
)
from hr_agents.providers.calendar import GoogleCalendarConfig

START = datetime(2026, 11, 2, 1, 0, tzinfo=UTC)
END = START + timedelta(hours=8)
TOKEN_URL = "https://oauth2.googleapis.com/token"
FREEBUSY_URL = "https://www.googleapis.com/calendar/v3/freeBusy"

CONFIG = GoogleCalendarConfig(
    client_id="client-1",
    client_secret=SecretStr("secret-1"),
    refresh_token=SecretStr("refresh-1"),
    calendar_id="primary",
)


def make_adapter(**kwargs: object) -> GoogleCalendarBusy:
    clock = kwargs.pop("clock", None)
    if callable(clock):
        return GoogleCalendarBusy(CONFIG, clock=clock)
    return GoogleCalendarBusy(CONFIG)


def token_response(token: str = "access-1", expires_in: int = 3600) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": token, "expires_in": expires_in, "token_type": "Bearer"}
    )


def busy_response(*windows: tuple[str, str]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "kind": "calendar#freeBusy",
            "calendars": {
                "primary": {
                    "busy": [{"start": start, "end": end} for start, end in windows],
                    "errors": [],
                }
            },
        },
    )


@respx.mock
def test_refreshes_a_token_and_returns_sorted_busy_windows() -> None:
    token = respx.post(TOKEN_URL).mock(return_value=token_response())
    freebusy = respx.post(FREEBUSY_URL).mock(
        return_value=busy_response(
            ("2026-11-02T05:00:00Z", "2026-11-02T06:30:00Z"),
            ("2026-11-02T02:00:00Z", "2026-11-02T03:00:00Z"),
        )
    )

    slots = make_adapter().busy(start=START, end=END)

    assert [slot.start_utc.hour for slot in slots] == [2, 5]
    token_request = token.calls[0].request
    assert token_request.headers["content-type"] == "application/x-www-form-urlencoded"
    form = dict(pair.split("=", 1) for pair in token_request.content.decode().split("&"))
    assert form["grant_type"] == "refresh_token"
    assert form["refresh_token"] == "refresh-1"
    body = json.loads(freebusy.calls[0].request.content)
    assert body == {
        "timeMin": "2026-11-02T01:00:00Z",
        "timeMax": "2026-11-02T09:00:00Z",
        "items": [{"id": "primary"}],
    }
    assert freebusy.calls[0].request.headers["Authorization"] == "Bearer access-1"


@respx.mock
def test_the_access_token_is_cached_until_it_expires() -> None:
    now = [1_000.0]
    tokens = respx.post(TOKEN_URL).mock(return_value=token_response(expires_in=3600))
    respx.post(FREEBUSY_URL).mock(return_value=busy_response())
    adapter = make_adapter(clock=lambda: now[0])

    adapter.busy(start=START, end=END)
    adapter.busy(start=START, end=END)
    assert tokens.call_count == 1

    now[0] += 3600  # past expiry (minus the safety margin)
    adapter.busy(start=START, end=END)
    assert tokens.call_count == 2


@respx.mock
def test_a_calendar_error_entry_is_refused() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.post(FREEBUSY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "calendars": {
                    "primary": {
                        "busy": [],
                        "errors": [{"domain": "global", "reason": "notFound"}],
                    }
                }
            },
        )
    )

    with pytest.raises(GoogleCalendarError, match="notFound"):
        make_adapter().busy(start=START, end=END)


@respx.mock
def test_a_rejected_refresh_is_a_named_refusal() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "Token has been expired"}
        )
    )

    with pytest.raises(GoogleCalendarError, match="invalid_grant"):
        make_adapter().busy(start=START, end=END)


@respx.mock
def test_a_transport_failure_is_a_named_refusal() -> None:
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("no route"))

    with pytest.raises(GoogleCalendarError, match="ConnectError"):
        make_adapter().busy(start=START, end=END)


@respx.mock
def test_a_malformed_interval_is_refused_rather_than_dropped() -> None:
    respx.post(TOKEN_URL).mock(return_value=token_response())
    respx.post(FREEBUSY_URL).mock(
        return_value=httpx.Response(
            200, json={"calendars": {"primary": {"busy": [{"start": "not a date"}], "errors": []}}}
        )
    )

    with pytest.raises(GoogleCalendarError, match="malformed"):
        make_adapter().busy(start=START, end=END)


def test_a_naive_bound_is_refused_before_any_request() -> None:
    with pytest.raises(GoogleCalendarError, match="timezone-aware"):
        make_adapter().busy(start=datetime(2026, 11, 2, 1, 0), end=datetime(2026, 11, 2, 9, 0))


def test_an_inverted_window_is_refused() -> None:
    with pytest.raises(GoogleCalendarError, match="end must be after start"):
        make_adapter().busy(start=END, end=START)
