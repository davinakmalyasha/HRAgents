"""Seed starter checklists and empty rate-table shells.

Safe to run repeatedly: templates are matched by name and rate tables by kind.
The rate tables carry **no values** and stay unverified; payroll flags them until
a named human enters the statutory numbers and certifies the source.

    uv run python scripts/seed_starters.py
"""

from __future__ import annotations

import argparse

from hr_agents.config import get_settings
from hr_agents.main import create_app
from hr_agents.setup import setup_actor
from hr_agents.starters import seed_starters


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed starter templates and rate-table shells")
    parser.add_argument(
        "--operator",
        help="who this setup content is filed under (default: HRAGENTS_ACTOR_NAME)",
    )
    args = parser.parse_args()

    operator = args.operator or get_settings().actor_name or "setup"
    app = create_app()
    report = seed_starters(app.state.people, actor=setup_actor(operator))

    if report.changed:
        for item in report.created:
            print(f"created  {item}")
    for item in report.skipped:
        print(f"skipped  {item}")
    print(
        f"\n{len(report.created)} created, {len(report.skipped)} already present. "
        "Rate tables are empty on purpose: enter and verify the statutory values."
    )
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
