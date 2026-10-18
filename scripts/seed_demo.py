"""Seed the demo dataset into the configured backend.

Uses the same composition root as the API, so ``HRAGENTS_STORE_BACKEND`` and
``HRAGENTS_DATABASE_URL`` decide where the rows land. Idempotent: the marker
employee number ``DEMO-001`` means a second run changes nothing.

    uv run python scripts/seed_demo.py
"""

from __future__ import annotations

from hr_agents.demo import seed_demo
from hr_agents.main import create_app


def main() -> int:
    app = create_app()
    report = seed_demo(app)
    if report.seeded:
        print(f"Seeded {report.employees} employees and {report.applications} applications.")
    else:
        print(report.note)
    if report.note and report.seeded:
        print(f"Note: {report.note}")
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
