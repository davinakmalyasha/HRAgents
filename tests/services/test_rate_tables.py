from uuid import uuid4

import pytest

from hr_agents.models import RateEntry, RateTableKind
from hr_agents.services import (
    RateTableError,
    RateTableService,
    RateTableStore,
)
from hr_agents.services.audit import AuditChain


@pytest.fixture
def service() -> RateTableService:
    return RateTableService(RateTableStore(), audit=AuditChain())


BPJS_ENTRY = RateEntry(
    label="Employer share",
    employer_share_percent=4.0,
    employee_share_percent=1.0,
    wage_cap=12_000_000.0,
)


def test_create_starts_unverified(service: RateTableService) -> None:
    table = service.create(
        kind=RateTableKind.BPJS_KESEHATAN, name="BPJS Kesehatan", created_by="hr-admin"
    )
    assert table.verified is False
    assert table.usable is False


def test_set_entries_invalidates_verification(service: RateTableService) -> None:
    table = service.create(
        kind=RateTableKind.BPJS_KESEHATAN, name="BPJS Kesehatan", created_by="hr"
    )
    service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    service.verify(table.id, verified_by="hr-admin", source_note="Permenkes 2024")

    edited = service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    assert edited.verified is False
    assert edited.verified_by is None


def test_verify_requires_source_note(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.PPH21_TER, name="TER", created_by="hr")
    service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    with pytest.raises(RateTableError, match="source note"):
        service.verify(table.id, verified_by="hr-admin", source_note="  ")


def test_verify_requires_entries(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.PPH21_TER, name="TER", created_by="hr")
    with pytest.raises(RateTableError, match="empty"):
        service.verify(table.id, verified_by="hr-admin", source_note="DJP")


def test_mark_verified_sets_metadata(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.THR_FORMULA, name="THR", created_by="hr")
    service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    verified = service.verify(table.id, verified_by="hr-admin", source_note="Permenaker 6/2016")
    assert verified.usable is True
    assert verified.verified_by == "hr-admin"
    assert verified.verified_at is not None


def test_unverified_listing(service: RateTableService) -> None:
    verified = service.create(
        kind=RateTableKind.BPJS_KETENAGAKERJAAN_JHT, name="JHT", created_by="hr"
    )
    service.set_entries(verified.id, entries=[BPJS_ENTRY], updated_by="hr")
    service.verify(verified.id, verified_by="hr-admin", source_note="BPJS")

    service.create(kind=RateTableKind.OVERTIME_PREMIUM, name="OT", created_by="hr")

    assert [table.kind for table in service.unverified()] == [RateTableKind.OVERTIME_PREMIUM]


def test_require_usable_raises_when_unverified(service: RateTableService) -> None:
    service.create(kind=RateTableKind.BPJS_JKM, name="JKM", created_by="hr")
    with pytest.raises(RateTableError, match="HR must enter and verify"):
        service.require_usable(RateTableKind.BPJS_JKM)


def test_require_usable_returns_verified_table(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.BPJS_JKM, name="JKM", created_by="hr")
    service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    service.verify(table.id, verified_by="hr-admin", source_note="BPJS")

    usable = service.require_usable(RateTableKind.BPJS_JKM)
    assert usable.id == table.id


def test_audit_trail(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.MINIMUM_WAGE, name="UMP", created_by="hr")
    service.set_entries(table.id, entries=[BPJS_ENTRY], updated_by="hr")
    service.verify(table.id, verified_by="hr-admin", source_note="Kemnaker")

    actions = [entry.action for entry in service._audit.entries]
    assert actions == [
        "rate_table.created",
        "rate_table.entries_updated",
        "rate_table.verified",
    ]
    assert service._audit.verify() == -1


def test_unknown_table_raises(service: RateTableService) -> None:
    with pytest.raises(RateTableError, match="unknown rate table"):
        service.get(uuid4())
