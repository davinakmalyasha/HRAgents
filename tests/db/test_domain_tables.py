"""Round-trip tests for the people, compliance, growth, and offboarding tables.

These run against in-memory SQLite (no Docker required) and verify that the
SQLAlchemy mappings accept and return the shapes the services write.
"""

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from hr_agents.db import compliance_tables as ct
from hr_agents.db import growth_tables as gt
from hr_agents.db import offboarding_tables as ot
from hr_agents.db import people_tables as pt
from hr_agents.db.base import Base


@pytest.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    await engine.dispose()


async def test_metadata_registers_all_domain_tables() -> None:
    names = set(Base.metadata.tables)
    assert {
        "employees",
        "org_units",
        "employee_documents",
        "contracts",
        "approvals",
        "tasks",
        "rate_tables",
        "consent_records",
        "retention_policies",
        "retention_records",
        "erasure_requests",
        "breach_incidents",
        "review_cycles",
        "review_assignments",
        "review_summaries",
        "goals",
        "offboarding_templates",
        "offboarding_plans",
        "offboarding_assets",
    } <= names


async def test_employee_core_round_trip(factory: async_sessionmaker[AsyncSession]) -> None:
    unit = pt.OrgUnitRecord(id=uuid4(), name="Engineering", cost_center="ENG")
    employee = pt.EmployeeRecord(
        id=uuid4(),
        full_name="Sari Dewi",
        email="sari@example.com",
        job_title="Finance Staff",
        org_unit_id=unit.id,
        status="active",
        emergency_contact={"name": "Budi", "phone": "0812"},
    )
    document = pt.EmployeeDocumentRecord(
        id=uuid4(),
        employee_id=employee.id,
        kind="ktp",
        storage_key="docs/ktp.pdf",
        sha256="a" * 64,
        status="claimed",
    )
    contract = pt.ContractRecord(
        id=uuid4(),
        employee_id=employee.id,
        contract_type="pkwt",
        start_date=date.today(),
        status="active",
        compensation_due=True,
    )

    async with factory() as session:
        session.add_all([unit, employee, document, contract])
        await session.commit()

    async with factory() as session:
        loaded = await session.get(pt.EmployeeRecord, employee.id)
        assert loaded is not None
        assert loaded.full_name == "Sari Dewi"
        assert loaded.emergency_contact is not None
        assert loaded.emergency_contact["name"] == "Budi"
        docs = (await session.execute(select(pt.EmployeeDocumentRecord))).scalars().all()
        assert docs[0].storage_key == "docs/ktp.pdf"
        contracts = (await session.execute(select(pt.ContractRecord))).scalars().all()
        assert contracts[0].compensation_due is True


async def test_consent_and_retention_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    consent = ct.ConsentRecordTable(
        id=uuid4(),
        subject_kind="candidate",
        subject_id="cand-1",
        purpose="recruitment_evaluation",
        lawful_basis="consent",
        granted=True,
        granted_at=datetime.now(UTC),
        captured_by="hr-admin",
    )
    policy = ct.RetentionPolicyTable(
        id=uuid4(),
        entity="candidate",
        name="Candidate records",
        retention_months=24,
        expiry_action="anonymize",
        updated_by="hr-admin",
    )
    record = ct.RetentionRecordTable(
        id=uuid4(),
        entity="candidate",
        subject_kind="candidate",
        subject_id="cand-1",
        anchor_at=consent.granted_at,
        legal_hold=True,
        legal_hold_reason="litigation",
        held_by="hr-admin",
    )

    async with factory() as session:
        session.add_all([consent, policy, record])
        await session.commit()

    async with factory() as session:
        loaded = await session.get(ct.ConsentRecordTable, consent.id)
        assert loaded is not None
        assert loaded.purpose == "recruitment_evaluation"
        loaded_policy = (await session.execute(select(ct.RetentionPolicyTable))).scalar_one()
        assert loaded_policy.retention_months == 24
        loaded_record = await session.get(ct.RetentionRecordTable, record.id)
        assert loaded_record is not None
        assert loaded_record.legal_hold is True


async def test_erasure_and_breach_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    erasure = ct.ErasureRequestTable(
        id=uuid4(),
        subject_kind="candidate",
        subject_id="cand-1",
        reason="UU PDP request",
        requested_by="hr-admin",
        received_at=datetime.now(UTC),
        status="received",
        dispositions=[],
    )
    incident = ct.BreachIncidentTable(
        id=uuid4(),
        title="Laptop lost",
        impact="high",
        status="open",
        discovered_at=erasure.received_at,
        discovered_by="it-ops",
        template_name="default_incident_checklist",
        steps=[{"key": "contain", "required": True}],
        notifications=[],
    )

    async with factory() as session:
        session.add_all([erasure, incident])
        await session.commit()

    async with factory() as session:
        loaded = await session.get(ct.ErasureRequestTable, erasure.id)
        assert loaded is not None
        assert loaded.dispositions == []
        loaded_incident = await session.get(ct.BreachIncidentTable, incident.id)
        assert loaded_incident is not None
        assert loaded_incident.steps[0]["key"] == "contain"


async def test_growth_tables_round_trip(factory: async_sessionmaker[AsyncSession]) -> None:
    cycle = gt.ReviewCycleRecord(
        id=uuid4(),
        name="2026 H1",
        kind="mid_year",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 6, 30),
        status="active",
        created_by="hr-admin",
    )
    assignment = gt.ReviewAssignmentRecord(
        id=uuid4(),
        cycle_id=cycle.id,
        employee_id=uuid4(),
        reviewer_id="lead-1",
        reviewer_role="manager",
        status="submitted",
        ratings={"delivery": 4.5},
    )
    summary = gt.ReviewSummaryRecord(
        id=uuid4(),
        cycle_id=cycle.id,
        employee_id=assignment.employee_id,
        status="pending_review",
        agent_draft="Strong delivery.",
        draft_by="agent:feedback_writer",
    )
    goal = gt.GoalRecord(
        id=uuid4(),
        employee_id=assignment.employee_id,
        title="Ship v2",
        status="active",
        progress_percent=40.0,
        created_by="hr-admin",
        updates=[{"progress_percent": 40.0, "by": "hr-admin"}],
    )

    async with factory() as session:
        session.add_all([cycle, assignment, summary, goal])
        await session.commit()

    async with factory() as session:
        loaded_assignment = (await session.execute(select(gt.ReviewAssignmentRecord))).scalar_one()
        assert loaded_assignment.ratings == {"delivery": 4.5}
        loaded_summary = await session.get(gt.ReviewSummaryRecord, summary.id)
        assert loaded_summary is not None
        assert loaded_summary.agent_draft == "Strong delivery."
        loaded_goal = await session.get(gt.GoalRecord, goal.id)
        assert loaded_goal is not None
        assert loaded_goal.updates[0]["by"] == "hr-admin"


async def test_offboarding_tables_round_trip(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    template = ot.OffboardingTemplateRecord(
        id=uuid4(),
        name="Resignation — starter",
        steps=[{"key": "handover", "required": True}],
    )
    plan = ot.OffboardingPlanRecord(
        id=uuid4(),
        employee_id=uuid4(),
        reason="resignation",
        last_working_day=date(2026, 10, 1),
        template_id=template.id,
        template_name=template.name,
        template_version_hash="b" * 64,
        steps=[],
        handover_notes=[],
    )
    asset = ot.OffboardingAssetRecord(
        id=uuid4(),
        employee_id=plan.employee_id,
        plan_id=plan.id,
        name="MacBook Pro",
        asset_code="MB-001",
        status="assigned",
    )

    async with factory() as session:
        session.add_all([template, plan, asset])
        await session.commit()

    async with factory() as session:
        loaded_plan = await session.get(ot.OffboardingPlanRecord, plan.id)
        assert loaded_plan is not None
        assert loaded_plan.template_version_hash == "b" * 64
        loaded_asset = await session.get(ot.OffboardingAssetRecord, asset.id)
        assert loaded_asset is not None
        assert loaded_asset.status == "assigned"
