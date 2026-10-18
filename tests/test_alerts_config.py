"""Alert rules must only reference metrics this build actually exposes.

Rules drift the moment a metric is renamed or dropped: the alert silently stops
firing, which is worse than having no alert. The guard reads the rules file and
checks every ``hragents_*`` series against the metrics module that renders it.

The two canaries — a stuck queue and a stale scheduler job — are asserted by
name because they are the product's core operational promises; deleting one
should be a conscious act, not a refactor casualty.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
RULES_PATH = REPO_ROOT / "ops" / "alerts" / "hragents.rules.yml"
METRICS_PATH = REPO_ROOT / "src" / "hr_agents" / "api" / "metrics.py"

SEVERITIES = {"info", "warning", "critical"}


def _rules() -> list[dict]:
    document = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return [rule for group in document["groups"] for rule in group["rules"]]


def test_every_rule_is_complete_and_named_uniquely() -> None:
    rules = _rules()
    names = [rule["alert"] for rule in rules]

    assert len(names) == len(set(names))
    for rule in rules:
        assert rule["expr"].strip(), rule["alert"]
        assert str(rule["for"]).endswith(("m", "s", "h", "d")), rule["alert"]
        assert rule["labels"]["severity"] in SEVERITIES, rule["alert"]
        assert rule["annotations"]["summary"], rule["alert"]
        assert rule["annotations"]["description"], rule["alert"]


def test_every_referenced_metric_is_rendered_by_the_exposition() -> None:
    expressions = " ".join(rule["expr"] for rule in _rules())
    referenced = set(re.findall(r"\bhragents_[a-z_]+\b", expressions))
    assert referenced, "the rules must name at least one hragents series"

    source = METRICS_PATH.read_text(encoding="utf-8")
    missing = sorted(name for name in referenced if name not in source)
    assert missing == [], f"rules reference series the API does not render: {missing}"


def test_the_two_canaries_stay_alerted_on() -> None:
    names = {rule["alert"] for rule in _rules()}
    assert "HRAgentsStuckQueuedApplications" in names
    assert "HRAgentsSchedulerJobStale" in names
    assert "HRAgentsDeadLetteredMessages" in names
