"""A demo dataset for a fresh install.

The story: a small Indonesian company mid-onboarding, mid-hiring and one
payroll period into the month. Everything is created through the real services,
so the audit trail, the approval queue, the retention ledger and the task
engine all contain what the demo screens show.

Two deliberate choices:

- the statutory rate tables are seeded **unverified**. Payroll refuses to
  compute on a table no human has checked against a source, and a demo that
  bypassed that gate would be teaching the wrong lesson about the product's
  central safety property;
- the marker employee number ``DEMO-001`` makes the seed idempotent: a second
  run changes nothing.

``scripts/seed_demo.py`` is the CLI; this module is importable so the test
suite can seed into an in-memory app and assert the result.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import FastAPI

from hr_agents.identity import ActorProvenance, ActorRef, ActorType
from hr_agents.models import (
    AccrualMethod,
    ApproverRole,
    ContractType,
    DocumentKind,
    Employee,
    JobFamily,
    JobStatus,
    LeaveType,
    LeaveTypePolicy,
    OrgUnit,
    PayrollRunKind,
    RateEntry,
    RateTableKind,
    RecordEntity,
    StepKind,
    SubjectKind,
    TemplateStep,
    business_today,
)
from hr_agents.models.money import money as m
from hr_agents.rbac import RoleId
from hr_agents.services.ingestion import SubmissionInput
from hr_agents.services.rate_tables import RateTableService

DEMO_MARKER = "DEMO-001"


def demo_actor() -> ActorRef:
    """The seeder as an authenticated HR administrator.

    A legacy string would be refused where a record belongs to somebody (the
    leave request, for one): the permission table is the authority, so the
    actor has to carry a role the auth layer could have produced.
    """
    return ActorRef(
        actor_id="demo-seed",
        actor_type=ActorType.HUMAN,
        provenance=ActorProvenance.AUTHENTICATED,
        role=RoleId.HR_ADMIN.value,
    )


@dataclass
class DemoSeedReport:
    seeded: bool
    employees: int = 0
    applications: int = 0
    note: str = ""


def seed_demo(app: FastAPI) -> DemoSeedReport:
    """Create the demo dataset once. Returns what happened, not just success."""
    people = app.state.people
    store = app.state.store
    actor = demo_actor()
    today = business_today()

    if any(
        employee.employee_number == DEMO_MARKER for employee in people.employees.list_employees()
    ):
        return DemoSeedReport(
            seeded=False,
            note="demo dataset already present (DEMO-001 exists); nothing changed",
        )

    engineering = people.employees.create_org_unit(
        name="Engineering", actor=actor, cost_center="ENG"
    )
    finance = people.employees.create_org_unit(name="Finance", actor=actor, cost_center="FIN")
    people_ops = people.employees.create_org_unit(
        name="People Operations", actor=actor, cost_center="POP"
    )

    def hire(
        number: str,
        name: str,
        title: str,
        unit: OrgUnit,
        *,
        hired_days_ago: int,
        probation_end: date | None = None,
    ) -> Employee:
        return people.employees.create(
            full_name=name,
            actor=actor,
            email=f"{name.split()[0].lower()}@example.com",
            phone="+62-812-000-0000",
            job_title=title,
            org_unit_id=unit.id,
            work_location="Jakarta",
            hire_date=today - timedelta(days=hired_days_ago),
            probation_end_date=probation_end,
            employee_number=number,
        )

    ayu = hire("DEMO-001", "Ayu Lestari", "Finance Staff", finance, hired_days_ago=500)
    budi = hire(
        "DEMO-002",
        "Budi Santoso",
        "Backend Engineer",
        engineering,
        hired_days_ago=800,
    )
    hire(
        "DEMO-003",
        "Citra Dewi",
        "Operations Lead",
        people_ops,
        hired_days_ago=600,
    )
    dimas = hire(
        "DEMO-004",
        "Dimas Prakoso",
        "Data Analyst",
        engineering,
        hired_days_ago=30,
        probation_end=today + timedelta(days=60),
    )
    hire("DEMO-005", "Eka Putri", "Finance Staff", finance, hired_days_ago=200)

    permanent = people.contracts.create(
        employee_id=budi.id,
        contract_type=ContractType.PKWTT,
        start_date=today - timedelta(days=800),
        actor=actor,
    )
    people.contracts.activate(permanent.id, actor=actor)
    fixed_term = people.contracts.create(
        employee_id=dimas.id,
        contract_type=ContractType.PKWT,
        start_date=today - timedelta(days=30),
        end_date=today + timedelta(days=335),
        actor=actor,
    )
    people.contracts.activate(fixed_term.id, actor=actor)

    for owner, kind, name in (
        (ayu, DocumentKind.KTP, "ktp-ayu.pdf"),
        (dimas, DocumentKind.KTP, "ktp-dimas.pdf"),
    ):
        people.employees.add_document(
            owner.id,
            kind=kind,
            storage_key=f"demo/{name}",
            sha256="a" * 64,
            actor=actor,
            filename=name,
            expires_on=today + timedelta(days=20 if owner is ayu else 120),
        )

    people.leave.set_policy(
        LeaveTypePolicy(
            leave_type=LeaveType.ANNUAL,
            name="Annual leave",
            paid=True,
            approver_role=ApproverRole.MANAGER,
            accrual_method=AccrualMethod.FLAT_MONTHLY,
            days_per_month=1.5,
            max_days_per_request=12,
            working_days_only=True,
        ),
        actor=actor,
    )
    next_monday = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    people.leave.request(
        employee_id=ayu.id,
        leave_type=LeaveType.ANNUAL,
        start_date=next_monday,
        end_date=next_monday + timedelta(days=2),
        actor=actor,
        reason="Family event in Bandung",
    )

    _seed_rate_tables(people.rate_tables, actor=actor)
    people.payroll.create_run(
        period_year=today.year,
        period_month=today.month,
        actor=actor,
        kind=PayrollRunKind.MONTHLY,
    )

    job = app.state.recruiting.jobs.create(
        title="Backend Engineer",
        actor=actor,
        description="Own the API behind the HR workspace.",
        must_have_skills=["Python", "PostgreSQL"],
        nice_to_have_skills=["FastAPI", "Docker"],
        stack=["Python", "PostgreSQL"],
        min_years_experience=3,
        job_family=JobFamily.ENGINEERING,
        status=JobStatus.OPEN,
    )
    applications = 0
    for candidate_name in ("Rani Wijaya", "Fajar Nugroho"):
        record, created = store.submit(
            SubmissionInput(
                job_id=job.id,
                source_channel="demo",
                consent_granted=True,
                candidate_name=candidate_name,
                candidate_emails=[f"{candidate_name.split()[0].lower()}@example.com"],
            )
        )
        if created:
            applications += 1
            app.state.audit.append(
                actor=actor.audit_actor(),
                action="application.received",
                subject_type="application",
                subject_id=str(record.id),
                payload={"source_channel": "demo", "candidate_name": candidate_name},
            )
            people.compliance.track_record(
                entity=RecordEntity.APPLICATION,
                subject_kind=SubjectKind.CANDIDATE,
                subject_id=str(record.candidate_id),
                actor=actor,
                label=candidate_name,
            )

    template = people.onboarding.create_template(
        name="Engineering starter",
        actor=actor,
        description="First week for a new engineer.",
        steps=[
            TemplateStep(
                key="collect_ktp",
                title="Collect KTP",
                kind=StepKind.DOCUMENT,
                document_kind=DocumentKind.KTP,
                due_days_after_hire=3,
            ),
            TemplateStep(
                key="sign_contract",
                title="Sign the employment contract",
                kind=StepKind.CONTRACT,
                due_days_after_hire=1,
                requires_human_signoff=False,
            ),
            TemplateStep(
                key="read_handbook",
                title="Read the employee handbook",
                kind=StepKind.ORIENTATION,
                due_days_after_hire=7,
            ),
        ],
    )
    people.onboarding.start_plan(employee_id=dimas.id, template_id=template.id, actor=actor)

    cycle = people.growth.create_cycle(
        name=f"{today.year} mid-year review",
        period_start=today - timedelta(days=90),
        period_end=today + timedelta(days=90),
        actor=actor,
        submission_due_on=today + timedelta(days=30),
    )
    people.growth.add_assignment(
        cycle.id,
        employee_id=budi.id,
        reviewer_id="citra",
        actor=actor,
    )

    return DemoSeedReport(
        seeded=True,
        employees=5,
        applications=applications,
        note=(
            "Rate tables are seeded unverified on purpose: payroll refuses to "
            "compute until a named human verifies them against a real source."
        ),
    )


def _seed_rate_tables(rate_tables: RateTableService, *, actor: ActorRef) -> None:
    """Illustrative statutory shapes, left **unverified** for a human to check."""
    shares = (
        (RateTableKind.BPJS_KESEHATAN, 4.0, 1.0, 12_000_000.0),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JHT, 3.7, 2.0, None),
        (RateTableKind.BPJS_KETENAGAKERJAAN_JP, 2.0, 1.0, 10_000_000.0),
        (RateTableKind.BPJS_JKK, 0.24, None, None),
        (RateTableKind.BPJS_JKM, 0.3, None, None),
    )
    for kind, employer, employee, wage_cap in shares:
        table = rate_tables.create(kind=kind, name=kind.value, actor=actor)
        rate_tables.set_entries(
            table.id,
            entries=[
                RateEntry(
                    label="illustrative row",
                    employer_share_percent=employer,
                    employee_share_percent=employee,
                    wage_cap=m(wage_cap) if wage_cap is not None else None,
                )
            ],
            actor=actor,
        )

    overtime = rate_tables.create(kind=RateTableKind.OVERTIME_PREMIUM, name="Overtime", actor=actor)
    rate_tables.set_entries(
        overtime.id,
        entries=[
            RateEntry(key="monthly_hours", label="Monthly hours", hours_per_month=173.0),
            RateEntry(key="first_hour", label="First hour each day", multiplier=1.5),
            RateEntry(key="subsequent_hour", label="Subsequent hours", multiplier=2.0),
        ],
        actor=actor,
    )

    ptkp = rate_tables.create(kind=RateTableKind.PPH21_PTKP, name="PTKP", actor=actor)
    rate_tables.set_entries(
        ptkp.id,
        entries=[
            RateEntry(key="personal", label="Self", flat_amount=m(54_000_000)),
            RateEntry(key="dependent", label="Per dependent", flat_amount=m(6_750_000)),
        ],
        actor=actor,
    )

    minimum = rate_tables.create(kind=RateTableKind.MINIMUM_WAGE, name="Minimum wage", actor=actor)
    rate_tables.set_entries(
        minimum.id,
        entries=[RateEntry(label="Illustrative regional minimum", flat_amount=m(2_500_000))],
        actor=actor,
    )

    thr = rate_tables.create(kind=RateTableKind.THR_FORMULA, name="THR", actor=actor)
    rate_tables.set_entries(
        thr.id,
        entries=[
            RateEntry(key="under_1y", label="Under 1 year", multiplier=1.0),
            RateEntry(key="1y", label="1 to under 2 years", multiplier=2.0),
            RateEntry(key="2y", label="2 to under 3 years", multiplier=3.0),
            RateEntry(key="8y_plus", label="8 years and over", multiplier=10.0),
        ],
        actor=actor,
    )

    ter = rate_tables.create(kind=RateTableKind.PPH21_TER, name="TER", actor=actor)
    rate_tables.set_entries(
        ter.id,
        entries=[
            RateEntry(
                label="low",
                lower_bound=m(0),
                upper_bound=m(10_000_000),
                employee_share_percent=2.0,
            ),
            RateEntry(
                label="mid",
                lower_bound=m(10_000_000.1),
                upper_bound=m(30_000_000),
                employee_share_percent=5.0,
            ),
        ],
        actor=actor,
    )
