from uuid import uuid4

import pytest
from tests.actors import finance as finance_principal

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
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
        kind=RateTableKind.BPJS_KESEHATAN, name="BPJS Kesehatan", actor=ActorRef.legacy("hr-admin")
    )
    assert table.verified is False
    assert table.usable is False


def test_set_entries_invalidates_verification(service: RateTableService) -> None:
    table = service.create(
        kind=RateTableKind.BPJS_KESEHATAN, name="BPJS Kesehatan", actor=ActorRef.legacy("hr")
    )
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    service.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="Permenkes 2024")

    edited = service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    assert edited.verified is False
    assert edited.verified_by is None


def test_verify_requires_source_note(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.PPH21_TER, name="TER", actor=ActorRef.legacy("hr"))
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    with pytest.raises(RateTableError, match="source note"):
        service.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="  ")


def test_verify_requires_entries(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.PPH21_TER, name="TER", actor=ActorRef.legacy("hr"))
    with pytest.raises(RateTableError, match="empty"):
        service.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="DJP")


@pytest.mark.parametrize(
    "actor",
    [
        ActorRef.agent("payroll_bot"),
        ActorRef.system("scheduler"),
        ActorRef.system("worker"),
        ActorRef.legacy("system"),
        ActorRef.legacy("scheduler"),
    ],
)
def test_only_a_person_may_certify_a_statutory_rate_table(
    service: RateTableService, actor: ActorRef
) -> None:
    """The last ungated consequential operation, and the one AGENTS.md names.

    `verify` is the `verified` gate that `require_usable` reads before payroll
    will consume a table. Its own docstring admitted it "does not yet insist on
    that person being a person". The HTTP route was behind `RATES_VERIFY`, so the
    hole was not reachable over the API -- but this service is constructed in
    `PeopleServices` and reachable in-process by the worker, the scheduler and any
    tool, and every other consequential operation here checks at this layer.
    """
    table = service.create(
        kind=RateTableKind.BPJS_KESEHATAN, name="BPJS 2026", actor=ActorRef.legacy("hr")
    )
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))

    with pytest.raises(RateTableError, match="named human"):
        service.verify(table.id, actor=actor, source_note="Permenaker 6/2016")

    unverified = service.get(table.id)
    assert unverified.usable is False
    assert unverified.verified_by is None
    # And payroll still refuses it.
    with pytest.raises(RateTableError):
        service.require_usable(RateTableKind.BPJS_KESEHATAN)


def test_verification_is_recorded_against_the_person_who_did_it(
    service: RateTableService,
) -> None:
    """Provenance, not just the name: the chain has to say a person certified it."""
    chain = service._audit
    table = service.create(kind=RateTableKind.THR_FORMULA, name="THR", actor=ActorRef.legacy("hr"))
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))

    service.verify(table.id, actor=finance_principal("Sari"), source_note="PP 36/2025")

    entry = [item for item in chain.entries if item.action == "rate_table.verified"]
    assert len(entry) == 1
    assert entry[0].actor.actor_id == "Sari"
    assert entry[0].actor.actor_type is ActorType.HUMAN
    assert entry[0].actor.provenance is ActorProvenance.AUTHENTICATED


def test_mark_verified_sets_metadata(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.THR_FORMULA, name="THR", actor=ActorRef.legacy("hr"))
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    verified = service.verify(
        table.id, actor=ActorRef.legacy("hr-admin"), source_note="Permenaker 6/2016"
    )
    assert verified.usable is True
    assert verified.verified_by == "hr-admin"
    assert verified.verified_at is not None


def test_unverified_listing(service: RateTableService) -> None:
    verified = service.create(
        kind=RateTableKind.BPJS_KETENAGAKERJAAN_JHT, name="JHT", actor=ActorRef.legacy("hr")
    )
    service.set_entries(verified.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    service.verify(verified.id, actor=ActorRef.legacy("hr-admin"), source_note="BPJS")

    service.create(kind=RateTableKind.OVERTIME_PREMIUM, name="OT", actor=ActorRef.legacy("hr"))

    assert [table.kind for table in service.unverified()] == [RateTableKind.OVERTIME_PREMIUM]


def test_require_usable_raises_when_unverified(service: RateTableService) -> None:
    service.create(kind=RateTableKind.BPJS_JKM, name="JKM", actor=ActorRef.legacy("hr"))
    with pytest.raises(RateTableError, match="HR must enter and verify"):
        service.require_usable(RateTableKind.BPJS_JKM)


def test_require_usable_returns_verified_table(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.BPJS_JKM, name="JKM", actor=ActorRef.legacy("hr"))
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    service.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="BPJS")

    usable = service.require_usable(RateTableKind.BPJS_JKM)
    assert usable.id == table.id


def test_audit_trail(service: RateTableService) -> None:
    table = service.create(kind=RateTableKind.MINIMUM_WAGE, name="UMP", actor=ActorRef.legacy("hr"))
    service.set_entries(table.id, entries=[BPJS_ENTRY], actor=ActorRef.legacy("hr"))
    service.verify(table.id, actor=ActorRef.legacy("hr-admin"), source_note="Kemnaker")

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
