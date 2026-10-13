"""Business dates are read in the business zone, and only one place reads them.

`date.today()` reads the *host's* calendar day. On the UTC container this project
ships in, that is wrong for the seven hours after Jakarta has already rolled
over: a leave request filed "today" lands on yesterday, a probation ending
"today" ends tomorrow, and the due-date sweeps fire a day early or late. The
boundary is deterministic, so it is tested by construction rather than by
waiting for 17:00 UTC.
"""

from __future__ import annotations

import pathlib
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from hr_agents.config import Settings
from hr_agents.models import business_timezone, business_today, set_business_timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

# The only two files allowed to contain the literal text: both do so in prose
# explaining why calling it is wrong.
PROSE_ONLY = {"hr_agents/models/common.py", "hr_agents/config.py"}


@pytest.fixture(autouse=True)
def jakarta() -> None:
    """Every test starts in the default zone, whatever ran before it."""
    set_business_timezone("Asia/Jakarta")


def test_the_boundary_is_where_jakarta_midnight_is() -> None:
    """16:59 UTC is still the 1st in Jakarta; 17:00 UTC is already the 2nd.

    This is the exact bug: both instants are the same calendar day on a UTC host.
    """
    before = datetime(2026, 1, 1, 16, 59, tzinfo=UTC)
    after = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)

    assert business_today(before) == date(2026, 1, 1)
    assert business_today(after) == date(2026, 1, 2)


def test_the_host_calendar_day_is_not_consulted() -> None:
    """A UTC-configured install reads UTC dates, because that is what was asked for."""
    set_business_timezone("UTC")
    moment = datetime(2026, 1, 1, 17, 0, tzinfo=UTC)

    assert business_today(moment) == date(2026, 1, 1)


def test_configured_zone_is_honoured_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scripts and the scheduler read the env lazily, so this covers them too."""
    monkeypatch.setenv("HRAGENTS_TIMEZONE", "Pacific/Kiritimati")  # UTC+14
    set_business_timezone(None)
    moment = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

    assert business_timezone().key == "Pacific/Kiritimati"
    assert business_today(moment) == date(2026, 1, 2)


def test_without_configuration_the_default_is_jakarta() -> None:
    set_business_timezone(None)
    assert business_timezone().key == "Asia/Jakarta"


def test_a_naive_datetime_is_refused() -> None:
    """An aware instant is the only kind that means the same thing on every host."""
    with pytest.raises(ValueError, match="aware datetime"):
        business_today(datetime(2026, 1, 1, 12, 0))


def test_an_unknown_zone_stops_startup() -> None:
    """A typo must fail loudly, not silently fall back to Jakarta dates."""
    with pytest.raises(ValidationError, match="unknown timezone"):
        Settings(timezone="Not/AZone")


def test_the_default_setting_matches_the_helper_default() -> None:
    assert Settings().timezone == "Asia/Jakarta"


def test_no_module_reads_the_host_calendar_day() -> None:
    """The guard: business dates have exactly one source.

    A new `date.today()` reintroduces a bug that is invisible on a laptop in
    Jakarta and wrong for seven hours every day on the server it deploys to, so
    the check is structural rather than one service at a time.
    """
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        relative = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        if "date.today()" not in text:
            continue
        if relative not in PROSE_ONLY:
            offenders.append(relative)

    assert offenders == [], (
        f"these modules call date.today(); use hr_agents.models.business_today instead: {offenders}"
    )
