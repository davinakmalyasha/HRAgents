"""Export a legacy Python-backend database to `hragents-export/1` JSON.

This is the direct-database migration path: run it on any machine that can
reach the legacy database (Postgres in production, SQLite for a trial), copy
the JSON file to the HR laptop, then import it with the desktop CLI::

    uv run python scripts/export_legacy.py hragents-export-2026-11-03.json
    hragents-cli import hragents-export-2026-11-03.json        # dry-run first
    hragents-cli import hragents-export-2026-11-03.json --commit

Read-only by construction: `iter_export` opens one short read transaction per
table and never writes. Binary attachments stay in object storage (see
`docs/deployment.md`); every database row describing them is included.

Usage:
    HRAGENTS_DATABASE_URL=postgresql://user:pass@host:5432/hr \\
        uv run python scripts/export_legacy.py [output-path]
    HRAGENTS_DATABASE_URL=sqlite:////path/to/hr.db \\
        uv run python scripts/export_legacy.py [output-path]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from hr_agents.db import (  # noqa: F401 — register every table on the metadata
    compliance_tables,
    growth_tables,
    leave_tables,
    offboarding_tables,
    offers_tables,
    onboarding_tables,
    payroll_tables,
    people_tables,
    tables,
    workspace_tables,
)
from hr_agents.models import utc_now
from hr_agents.services.export import export_filename, iter_export


def main() -> int:
    database_url = os.environ.get("HRAGENTS_DATABASE_URL", "").strip()
    if not database_url:
        print(
            "HRAGENTS_DATABASE_URL is not set; nothing to export. "
            "Example: HRAGENTS_DATABASE_URL=postgresql://user:pass@host:5432/hr",
            file=sys.stderr,
        )
        return 2
    moment = utc_now()
    output = Path(sys.argv[1] if len(sys.argv) > 1 else export_filename(moment))
    try:
        engine = create_engine(database_url)
        factory = sessionmaker(engine, expire_on_commit=False)
        exported_by = os.environ.get("HRAGENTS_EXPORT_BY", "hr-operator").strip() or "hr-operator"
        with output.open("w", encoding="utf-8") as handle:
            for chunk in iter_export(factory, exported_at=moment, exported_by=exported_by):
                handle.write(chunk)
    except Exception as error:  # fail closed: no partial file left behind
        output.unlink(missing_ok=True)
        print(f"export failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote {output} ({export_filename(moment)} format hragents-export/1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
