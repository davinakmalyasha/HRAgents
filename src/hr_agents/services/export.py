"""Full-tenant export: every row the application owns, as one JSON document.

The promise that every decision is reconstructible is only credible if the
operator can take the record with them. This walks the SQLAlchemy metadata
rather than a hand-maintained list, so a table added later is exported by
default instead of quietly missing from every backup story.

The export is streamed table by table with a short read transaction per table.
That keeps memory flat on a large payroll history and means one reader cannot
pin a long transaction across the whole database. Each table's snapshot is
independent; the manifest says so rather than implying a single point in time.

Binary attachments are *not* embedded: they live in object storage (MinIO or
S3), and `docs/deployment.md` covers exporting that bucket separately. The
database rows that describe them — names, kinds, owners, hashes if present —
are included.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.base import Base
from hr_agents.db.session import sync_session_scope

EXPORT_FORMAT = "hragents-export/1"


def export_tables() -> list[str]:
    """Every mapped table, sorted, which is the export's table of contents."""
    return sorted(Base.metadata.tables)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def iter_export(
    session_factory: sessionmaker[Session],
    *,
    exported_at: datetime,
    exported_by: str,
) -> Iterator[str]:
    """Yield one JSON document, table by table, without holding it all in memory."""
    tables = export_tables()
    header = {
        "format": EXPORT_FORMAT,
        "exported_at": exported_at.isoformat(),
        "exported_by": exported_by,
        "tables": tables,
        "snapshot": "one read transaction per table; the export is not a single point in time",
        "excluded": [
            "binary attachments in object storage (export the bucket separately)",
            "provider-side data held by the integrations the operator configured",
        ],
    }
    yield '{"manifest": ' + json.dumps(header, ensure_ascii=False) + ', "data": {'
    for index, name in enumerate(tables):
        if index:
            yield ", "
        table = Base.metadata.tables[name]
        with sync_session_scope(session_factory) as session:
            count = session.scalar(select(func.count()).select_from(table)) or 0
            yield f'{json.dumps(name)}: {{"count": {count}, "rows": ['
            statement = select(table).execution_options(yield_per=1000)
            first = True
            for row in session.execute(statement).mappings():
                if not first:
                    yield ", "
                first = False
                yield json.dumps(_jsonable(dict(row)), ensure_ascii=False)
            yield "]}"
    yield "}}"


def export_filename(moment: datetime) -> str:
    return f"hragents-export-{moment.date().isoformat()}.json"
