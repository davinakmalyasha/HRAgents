"""The department clock's failure alert: one POST, never a raised exception."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import CapturingLogger

from hr_agents.services import scheduler as scheduler_module
from hr_agents.services.scheduler import (
    ScheduledJobResult,
    SchedulerReport,
    alert_payload,
    send_failure_alert,
)

NOW = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
WEBHOOK = "https://hooks.slack.example/services/T/B/X"


def report(*jobs: ScheduledJobResult, dry_run: bool = False) -> SchedulerReport:
    return SchedulerReport(started_at=NOW, finished_at=NOW, dry_run=dry_run, jobs=list(jobs))


class Recorder:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def __call__(self, url: str, *, json: dict[str, Any], timeout: float) -> object:
        self.calls.append((url, json, timeout))
        response = type("Response", (), {"status_code": self.status_code})
        return response()


def failed(name: str = "retention", error: str = "database unavailable") -> ScheduledJobResult:
    return ScheduledJobResult(name=name, ok=False, error=error)


def test_the_summary_names_the_failed_jobs_and_nothing_else() -> None:
    payload = alert_payload(
        report(ScheduledJobResult(name="approvals", changed=2), failed(), dry_run=True)
    )

    text = str(payload["text"])
    assert "1 of 2 job(s) failed" in text
    assert "retention" in text and "database unavailable" in text
    assert payload["dry_run"] is True
    assert payload["failed_jobs"] == [{"name": "retention", "error": "database unavailable"}]


def test_a_failed_run_posts_once_and_a_healthy_one_is_silent() -> None:
    recorder = Recorder()

    assert send_failure_alert(report(failed()), WEBHOOK, post=recorder) is True
    assert (
        send_failure_alert(report(ScheduledJobResult(name="approvals")), WEBHOOK, post=recorder)
        is False
    )
    assert not send_failure_alert(report(failed()), "", post=recorder)

    assert len(recorder.calls) == 1
    url, body, timeout = recorder.calls[0]
    assert url == WEBHOOK
    assert "retention" in str(body["text"])
    assert timeout == 5.0


def test_a_transport_failure_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(scheduler_module, "logger", logger)

    def unreachable(url: str, *, json: dict[str, Any], timeout: float) -> object:
        raise RuntimeError("no route to host")

    assert send_failure_alert(report(failed()), WEBHOOK, post=unreachable) is False
    events = [call.args[0] for call in logger.calls if call.args]
    assert "scheduler.alert_failed" in events


def test_an_error_response_is_reported_not_trusted() -> None:
    assert send_failure_alert(report(failed()), WEBHOOK, post=Recorder(500)) is False


def test_a_non_http_webhook_never_reaches_the_sender(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(scheduler_module, "logger", logger)
    recorder = Recorder()

    assert send_failure_alert(report(failed()), "ftp://example.com/hook", post=recorder) is False
    assert recorder.calls == []
    events = [call.args[0] for call in logger.calls if call.args]
    assert "scheduler.alert_skipped" in events


def test_plain_http_off_the_box_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    logger = CapturingLogger()
    monkeypatch.setattr(scheduler_module, "logger", logger)
    recorder = Recorder()

    assert (
        send_failure_alert(report(failed()), "http://chat.example.com/hook", post=recorder) is False
    )
    assert recorder.calls == []
    assert "scheduler.alert_skipped" in [call.args[0] for call in logger.calls if call.args]


def test_plain_http_to_loopback_still_works_for_a_local_sink() -> None:
    recorder = Recorder()
    assert (
        send_failure_alert(report(failed()), "http://localhost:8065/hooks/x", post=recorder) is True
    )
    assert recorder.calls[0][0] == "http://localhost:8065/hooks/x"


def test_plain_http_is_allowed_only_when_the_operator_opts_in() -> None:
    recorder = Recorder()
    assert (
        send_failure_alert(
            report(failed()),
            "http://mattermost.internal/hooks/x",
            post=recorder,
            allow_insecure_http=True,
        )
        is True
    )
    assert len(recorder.calls) == 1


def test_a_url_without_a_host_is_refused() -> None:
    recorder = Recorder()
    assert send_failure_alert(report(failed()), "https:///hook", post=recorder) is False
    assert recorder.calls == []
