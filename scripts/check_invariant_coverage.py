"""Fail when an invariant module loses branch coverage.

The global 90% floor lets a small, high-consequence module rot while the rest of
the suite grows. These five decide money and truth — scoring, policy routing,
queue priority, the audit chain and payroll — so they keep every line and branch
covered. Reads the JSON report pytest already writes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

INVARIANT_MODULES = (
    "hr_agents/services/scoring.py",
    "hr_agents/services/policy.py",
    "hr_agents/services/priority.py",
    "hr_agents/services/audit.py",
    "hr_agents/services/payroll.py",
)


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    path = Path(arguments[0] if arguments else ".coverage-invariants.json")
    if not path.is_file():
        print(f"error: coverage report {path} is missing", file=sys.stderr)
        return 1
    data = json.loads(path.read_text(encoding="utf-8"))
    files = data.get("files", {})

    failures: list[str] = []
    for module in INVARIANT_MODULES:
        matches = [info for name, info in files.items() if name.replace("\\", "/").endswith(module)]
        if not matches:
            failures.append(f"{module}: missing from the coverage report")
            continue
        summary = matches[0]["summary"]
        missing_lines = summary.get("missing_lines", [])
        missing_branches = summary.get("missing_branches", [])
        if summary.get("percent_covered", 0.0) < 100.0 or missing_lines or missing_branches:
            failures.append(
                f"{module}: {summary.get('percent_covered_display', '?')}% "
                f"(lines {missing_lines}, branches {missing_branches})"
            )
        else:
            print(f"ok   {module}")

    if failures:
        print("invariant coverage lost:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
