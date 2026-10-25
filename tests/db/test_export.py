"""The full export: every mapped table, valid JSON, values serialized."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db.audit import DbAuditChain
from hr_agents.services.export import (
    EXPORT_FORMAT,
    export_filename,
    export_tables,
    iter_export,
)

MOMENT = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def test_the_export_is_one_document_covering_every_table(
    factory: sessionmaker[Session],
) -> None:
    DbAuditChain(factory).append_system(
        action="test.event", subject_type="candidate", subject_id="c-1", payload={"n": 1}
    )

    document = "".join(iter_export(factory, exported_at=MOMENT, exported_by="hr-admin"))
    payload = json.loads(document)

    assert payload["manifest"]["format"] == EXPORT_FORMAT
    assert payload["manifest"]["exported_by"] == "hr-admin"
    assert payload["manifest"]["exported_at"] == MOMENT.isoformat()
    assert set(payload["manifest"]["tables"]) == set(export_tables())
    assert set(payload["data"]) == set(export_tables())

    audit = payload["data"]["audit_log"]
    assert audit["count"] >= 1
    assert audit["rows"][0]["action"] == "test.event"
    assert isinstance(audit["rows"][0]["created_at"], str)


def test_the_export_names_what_it_does_not_include(
    factory: sessionmaker[Session],
) -> None:
    payload = json.loads("".join(iter_export(factory, exported_at=MOMENT, exported_by="hr-admin")))

    excluded = " ".join(payload["manifest"]["excluded"]).lower()
    assert "attachment" in excluded
    assert "provider-side" in excluded
    assert "not a single point in time" in payload["manifest"]["snapshot"]


def test_the_filename_carries_the_date() -> None:
    assert export_filename(MOMENT) == "hragents-export-2026-10-24.json"
