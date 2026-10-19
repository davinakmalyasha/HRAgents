"""Postgres-backed compliance, growth, and offboarding stores.

Thin adapters over the generic mapping helpers; retention policies additionally
upsert by entity (one active policy per entity, matching the service contract).
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from hr_agents.db import compliance_tables as ct
from hr_agents.db import growth_tables as gt
from hr_agents.db import offboarding_tables as ot
from hr_agents.db.mapping import (
    add_model,
    delete_model,
    get_model,
    list_models,
    model_from_row,
    save_model,
)
from hr_agents.db.session import sync_session_scope
from hr_agents.models import (
    AssetStatus,
    AssignmentStatus,
    BreachIncident,
    ComplianceCalendarEntry,
    ConsentGrant,
    ErasureRequest,
    Goal,
    GoalStatus,
    OffboardingAsset,
    OffboardingPlan,
    OffboardingTemplate,
    RecordEntity,
    RetentionPolicy,
    RetentionRecord,
    ReviewAssignment,
    ReviewCycle,
    ReviewCycleStatus,
    ReviewSummary,
    SubjectKind,
)
from hr_agents.services.people_store import (
    ComplianceStore,
    GrowthStore,
    OffboardingStore,
)


class DbComplianceStore(ComplianceStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    # consent
    def add_consent(self, consent: ConsentGrant) -> None:
        add_model(self._session_factory, consent, ct.ConsentRecordTable)

    def save_consent(self, consent: ConsentGrant) -> None:
        save_model(self._session_factory, consent, ct.ConsentRecordTable)

    def get_consent(self, consent_id: UUID) -> ConsentGrant | None:
        return get_model(self._session_factory, ConsentGrant, ct.ConsentRecordTable, consent_id)

    def list_consents(self) -> list[ConsentGrant]:
        consents = list_models(self._session_factory, ConsentGrant, ct.ConsentRecordTable)
        return sorted(consents, key=lambda item: item.granted_at)

    def page_consents(
        self,
        *,
        subject_kind: SubjectKind | None,
        subject_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[list[ConsentGrant], int]:
        """The consent ledger in SQL: subject predicates, order, slice and count."""
        where = []
        if subject_kind is not None:
            where.append(ct.ConsentRecordTable.subject_kind == subject_kind.value)
        if subject_id is not None:
            where.append(ct.ConsentRecordTable.subject_id == subject_id)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(ct.ConsentRecordTable).where(*where)
            )
            rows = (
                session.execute(
                    select(ct.ConsentRecordTable)
                    .where(*where)
                    .order_by(ct.ConsentRecordTable.granted_at, ct.ConsentRecordTable.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ConsentGrant, row) for row in rows], int(total or 0)

    def delete_consent(self, consent_id: UUID) -> bool:
        """Issue the DELETE. Without this the inherited dict version reported False.

        The erasure workflow counts this return value and reads the handler's
        detail string as proof the store was mutated, so a `False` here became a
        `DELETED` disposition on the audit chain with the row still present.
        """
        with sync_session_scope(self._session_factory) as session:
            present = session.execute(
                select(ct.ConsentRecordTable.id).where(ct.ConsentRecordTable.id == consent_id)
            ).scalar_one_or_none()
            if present is None:
                return False
            session.execute(
                delete(ct.ConsentRecordTable).where(ct.ConsentRecordTable.id == consent_id)
            )
            return True

    def redact_consent(self, consent_id: UUID) -> ConsentGrant | None:
        """Blank the capture evidence in the database and return what was stored.

        Kept as one write rather than a read-modify-write so the two backends
        cannot drift on which fields count as evidence.
        """
        with sync_session_scope(self._session_factory) as session:
            session.execute(
                update(ct.ConsentRecordTable)
                .where(ct.ConsentRecordTable.id == consent_id)
                .values(
                    note="redacted on erasure",
                    capture_method="redacted",
                    captured_by="redacted",
                )
            )
        return self.get_consent(consent_id)

    # retention policies (one active policy per entity)
    def save_policy(self, policy: RetentionPolicy) -> None:
        with sync_session_scope(self._session_factory) as session:
            existing = session.execute(
                select(ct.RetentionPolicyTable).where(
                    ct.RetentionPolicyTable.entity == policy.entity.value
                )
            ).scalar_one_or_none()
            if existing is not None and existing.id != policy.id:
                session.delete(existing)
                session.flush()
        stored = get_model(
            self._session_factory, RetentionPolicy, ct.RetentionPolicyTable, policy.id
        )
        if stored is None:
            add_model(self._session_factory, policy, ct.RetentionPolicyTable)
        else:
            save_model(self._session_factory, policy, ct.RetentionPolicyTable)

    def get_policy(self, entity: RecordEntity) -> RetentionPolicy | None:
        with sync_session_scope(self._session_factory) as session:
            row = session.execute(
                select(ct.RetentionPolicyTable).where(
                    ct.RetentionPolicyTable.entity == entity.value
                )
            ).scalar_one_or_none()
            return None if row is None else model_from_row(RetentionPolicy, row)

    def list_policies(self) -> list[RetentionPolicy]:
        policies = list_models(self._session_factory, RetentionPolicy, ct.RetentionPolicyTable)
        return sorted(policies, key=lambda item: item.entity.value)

    # retention records
    def add_record(self, record: RetentionRecord) -> None:
        add_model(self._session_factory, record, ct.RetentionRecordTable)

    def save_record(self, record: RetentionRecord) -> None:
        save_model(self._session_factory, record, ct.RetentionRecordTable)

    def get_record(self, record_id: UUID) -> RetentionRecord | None:
        return get_model(self._session_factory, RetentionRecord, ct.RetentionRecordTable, record_id)

    def list_records(self) -> list[RetentionRecord]:
        records = list_models(self._session_factory, RetentionRecord, ct.RetentionRecordTable)
        return sorted(records, key=lambda item: item.anchor_at)

    def page_records(
        self,
        *,
        subject_kind: SubjectKind | None,
        subject_id: str | None,
        entity: RecordEntity | None,
        include_purged: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[RetentionRecord], int]:
        """The retention ledger in SQL: subject/entity filters and the purge gate.

        ``purged`` is derived from ``purged_at``, so the default view's predicate
        is ``purged_at IS NULL`` -- the same rule ``RetentionRecord.purged`` reads.
        """
        where = []
        if subject_kind is not None:
            where.append(ct.RetentionRecordTable.subject_kind == subject_kind.value)
        if subject_id is not None:
            where.append(ct.RetentionRecordTable.subject_id == subject_id)
        if entity is not None:
            where.append(ct.RetentionRecordTable.entity == entity.value)
        if not include_purged:
            where.append(ct.RetentionRecordTable.purged_at.is_(None))
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(ct.RetentionRecordTable).where(*where)
            )
            rows = (
                session.execute(
                    select(ct.RetentionRecordTable)
                    .where(*where)
                    .order_by(ct.RetentionRecordTable.anchor_at, ct.RetentionRecordTable.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(RetentionRecord, row) for row in rows], int(total or 0)

    # erasure requests
    def add_erasure(self, request: ErasureRequest) -> None:
        add_model(self._session_factory, request, ct.ErasureRequestTable)

    def save_erasure(self, request: ErasureRequest) -> None:
        save_model(self._session_factory, request, ct.ErasureRequestTable)

    def get_erasure(self, request_id: UUID) -> ErasureRequest | None:
        return get_model(self._session_factory, ErasureRequest, ct.ErasureRequestTable, request_id)

    def list_erasures(self) -> list[ErasureRequest]:
        requests = list_models(self._session_factory, ErasureRequest, ct.ErasureRequestTable)
        return sorted(requests, key=lambda item: item.received_at)

    def page_erasures(self, *, limit: int, offset: int) -> tuple[list[ErasureRequest], int]:
        """The erasure queue in SQL: ``(received_at, id)`` order, slice and count."""
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(select(func.count()).select_from(ct.ErasureRequestTable))
            rows = (
                session.execute(
                    select(ct.ErasureRequestTable)
                    .order_by(ct.ErasureRequestTable.received_at, ct.ErasureRequestTable.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ErasureRequest, row) for row in rows], int(total or 0)

    # breach incidents
    def add_incident(self, incident: BreachIncident) -> None:
        add_model(self._session_factory, incident, ct.BreachIncidentTable)

    def save_incident(self, incident: BreachIncident) -> None:
        save_model(self._session_factory, incident, ct.BreachIncidentTable)

    def get_incident(self, incident_id: UUID) -> BreachIncident | None:
        return get_model(self._session_factory, BreachIncident, ct.BreachIncidentTable, incident_id)

    def list_incidents(self) -> list[BreachIncident]:
        incidents = list_models(self._session_factory, BreachIncident, ct.BreachIncidentTable)
        return sorted(incidents, key=lambda item: item.discovered_at)

    def page_incidents(self, *, limit: int, offset: int) -> tuple[list[BreachIncident], int]:
        """The incident register in SQL: ``(discovered_at, id)`` order, slice and count."""
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(select(func.count()).select_from(ct.BreachIncidentTable))
            rows = (
                session.execute(
                    select(ct.BreachIncidentTable)
                    .order_by(ct.BreachIncidentTable.discovered_at, ct.BreachIncidentTable.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(BreachIncident, row) for row in rows], int(total or 0)

    # calendar entries
    def add_calendar_entry(self, entry: ComplianceCalendarEntry) -> None:
        add_model(self._session_factory, entry, ct.ComplianceCalendarEntryTable)

    def get_calendar_entry(self, entry_id: UUID) -> ComplianceCalendarEntry | None:
        return get_model(
            self._session_factory,
            ComplianceCalendarEntry,
            ct.ComplianceCalendarEntryTable,
            entry_id,
        )

    def list_calendar_entries(self) -> list[ComplianceCalendarEntry]:
        entries = list_models(
            self._session_factory, ComplianceCalendarEntry, ct.ComplianceCalendarEntryTable
        )
        return sorted(entries, key=lambda item: (item.due_on, str(item.id)))

    def delete_calendar_entry(self, entry_id: UUID) -> bool:
        return delete_model(self._session_factory, ct.ComplianceCalendarEntryTable, entry_id)


class DbGrowthStore(GrowthStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add_cycle(self, cycle: ReviewCycle) -> None:
        add_model(self._session_factory, cycle, gt.ReviewCycleRecord)

    def save_cycle(self, cycle: ReviewCycle) -> None:
        save_model(self._session_factory, cycle, gt.ReviewCycleRecord)

    def get_cycle(self, cycle_id: UUID) -> ReviewCycle | None:
        return get_model(self._session_factory, ReviewCycle, gt.ReviewCycleRecord, cycle_id)

    def list_cycles(self) -> list[ReviewCycle]:
        cycles = list_models(self._session_factory, ReviewCycle, gt.ReviewCycleRecord)
        return sorted(cycles, key=lambda item: item.created_at)

    def page_cycles(
        self, *, status: ReviewCycleStatus | None, limit: int, offset: int
    ) -> tuple[list[ReviewCycle], int]:
        """Cycles in SQL: optional status predicate, ``(created_at, id)``, count."""
        where = [] if status is None else [gt.ReviewCycleRecord.status == status.value]
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(gt.ReviewCycleRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(gt.ReviewCycleRecord)
                    .where(*where)
                    .order_by(gt.ReviewCycleRecord.created_at, gt.ReviewCycleRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ReviewCycle, row) for row in rows], int(total or 0)

    def add_assignment(self, assignment: ReviewAssignment) -> None:
        add_model(self._session_factory, assignment, gt.ReviewAssignmentRecord)

    def save_assignment(self, assignment: ReviewAssignment) -> None:
        save_model(self._session_factory, assignment, gt.ReviewAssignmentRecord)

    def get_assignment(self, assignment_id: UUID) -> ReviewAssignment | None:
        return get_model(
            self._session_factory, ReviewAssignment, gt.ReviewAssignmentRecord, assignment_id
        )

    def list_assignments(self) -> list[ReviewAssignment]:
        assignments = list_models(
            self._session_factory, ReviewAssignment, gt.ReviewAssignmentRecord
        )
        return sorted(assignments, key=lambda item: item.created_at)

    def page_assignments(
        self,
        *,
        cycle_id: UUID | None = None,
        reviewer_id: str | None = None,
        open_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[ReviewAssignment], int]:
        """Assignments in SQL: cycle and reviewer predicates, pending-only, count."""
        where = []
        if cycle_id is not None:
            where.append(gt.ReviewAssignmentRecord.cycle_id == cycle_id)
        if reviewer_id is not None:
            where.append(gt.ReviewAssignmentRecord.reviewer_id == reviewer_id)
        if open_only:
            where.append(gt.ReviewAssignmentRecord.status == AssignmentStatus.PENDING.value)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(gt.ReviewAssignmentRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(gt.ReviewAssignmentRecord)
                    .where(*where)
                    .order_by(gt.ReviewAssignmentRecord.created_at, gt.ReviewAssignmentRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ReviewAssignment, row) for row in rows], int(total or 0)

    def add_summary(self, summary: ReviewSummary) -> None:
        add_model(self._session_factory, summary, gt.ReviewSummaryRecord)

    def save_summary(self, summary: ReviewSummary) -> None:
        save_model(self._session_factory, summary, gt.ReviewSummaryRecord)

    def get_summary(self, summary_id: UUID) -> ReviewSummary | None:
        return get_model(self._session_factory, ReviewSummary, gt.ReviewSummaryRecord, summary_id)

    def list_summaries(self) -> list[ReviewSummary]:
        summaries = list_models(self._session_factory, ReviewSummary, gt.ReviewSummaryRecord)
        return sorted(summaries, key=lambda item: item.created_at)

    def page_summaries(
        self, *, cycle_id: UUID, limit: int, offset: int
    ) -> tuple[list[ReviewSummary], int]:
        """One cycle's summaries in SQL: predicate, ``(created_at, id)``, count."""
        where = [gt.ReviewSummaryRecord.cycle_id == cycle_id]
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(gt.ReviewSummaryRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(gt.ReviewSummaryRecord)
                    .where(*where)
                    .order_by(gt.ReviewSummaryRecord.created_at, gt.ReviewSummaryRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(ReviewSummary, row) for row in rows], int(total or 0)

    def add_goal(self, goal: Goal) -> None:
        add_model(self._session_factory, goal, gt.GoalRecord)

    def save_goal(self, goal: Goal) -> None:
        save_model(self._session_factory, goal, gt.GoalRecord)

    def get_goal(self, goal_id: UUID) -> Goal | None:
        return get_model(self._session_factory, Goal, gt.GoalRecord, goal_id)

    def list_goals(self) -> list[Goal]:
        goals = list_models(self._session_factory, Goal, gt.GoalRecord)
        return sorted(goals, key=lambda item: item.created_at)

    def page_goals(
        self,
        *,
        employee_id: UUID | None = None,
        status: GoalStatus | None = None,
        overdue_only: bool = False,
        as_of: date,
        limit: int,
        offset: int,
    ) -> tuple[list[Goal], int]:
        """Goals in SQL: owner and status predicates, past-due only, count.

        The overdue rule mirrors ``Goal.is_overdue`` exactly -- open (draft or
        active), dated, and due before ``as_of``.
        """
        where = []
        if employee_id is not None:
            where.append(gt.GoalRecord.employee_id == employee_id)
        if status is not None:
            where.append(gt.GoalRecord.status == status.value)
        if overdue_only:
            where.extend(
                [
                    gt.GoalRecord.status.in_([GoalStatus.DRAFT.value, GoalStatus.ACTIVE.value]),
                    gt.GoalRecord.due_on.is_not(None),
                    gt.GoalRecord.due_on < as_of,
                ]
            )
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(select(func.count()).select_from(gt.GoalRecord).where(*where))
            rows = (
                session.execute(
                    select(gt.GoalRecord)
                    .where(*where)
                    .order_by(gt.GoalRecord.created_at, gt.GoalRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(Goal, row) for row in rows], int(total or 0)


class DbOffboardingStore(OffboardingStore):
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        super().__init__()
        self._session_factory = session_factory

    def add_template(self, template: OffboardingTemplate) -> None:
        add_model(self._session_factory, template, ot.OffboardingTemplateRecord)

    def get_template(self, template_id: UUID) -> OffboardingTemplate | None:
        return get_model(
            self._session_factory, OffboardingTemplate, ot.OffboardingTemplateRecord, template_id
        )

    def list_templates(self) -> list[OffboardingTemplate]:
        templates = list_models(
            self._session_factory, OffboardingTemplate, ot.OffboardingTemplateRecord
        )
        return sorted(templates, key=lambda item: item.name.lower())

    def add_plan(self, plan: OffboardingPlan) -> None:
        add_model(self._session_factory, plan, ot.OffboardingPlanRecord)

    def save_plan(self, plan: OffboardingPlan) -> None:
        save_model(self._session_factory, plan, ot.OffboardingPlanRecord)

    def get_plan(self, plan_id: UUID) -> OffboardingPlan | None:
        return get_model(self._session_factory, OffboardingPlan, ot.OffboardingPlanRecord, plan_id)

    def list_plans(self) -> list[OffboardingPlan]:
        plans = list_models(self._session_factory, OffboardingPlan, ot.OffboardingPlanRecord)
        return sorted(plans, key=lambda item: item.started_at)

    def page_active_plans(self, *, limit: int, offset: int) -> tuple[list[OffboardingPlan], int]:
        """Active plans with ORDER BY (started_at, id) and LIMIT/OFFSET in SQL."""
        where = ot.OffboardingPlanRecord.completed_at.is_(None)
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(ot.OffboardingPlanRecord).where(where)
            )
            rows = (
                session.execute(
                    select(ot.OffboardingPlanRecord)
                    .where(where)
                    .order_by(ot.OffboardingPlanRecord.started_at, ot.OffboardingPlanRecord.id)
                    .offset(offset)
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [model_from_row(OffboardingPlan, row) for row in rows], int(total or 0)

    def add_asset(self, asset: OffboardingAsset) -> None:
        add_model(self._session_factory, asset, ot.OffboardingAssetRecord)

    def save_asset(self, asset: OffboardingAsset) -> None:
        save_model(self._session_factory, asset, ot.OffboardingAssetRecord)

    def get_asset(self, asset_id: UUID) -> OffboardingAsset | None:
        return get_model(
            self._session_factory, OffboardingAsset, ot.OffboardingAssetRecord, asset_id
        )

    def list_assets(self) -> list[OffboardingAsset]:
        assets = list_models(self._session_factory, OffboardingAsset, ot.OffboardingAssetRecord)
        return sorted(assets, key=lambda item: item.created_at)

    def page_assets(
        self,
        *,
        employee_id: UUID | None = None,
        plan_id: UUID | None = None,
        clearance_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[OffboardingAsset], int]:
        """The asset register in SQL: employee/plan predicates, clearance, count."""
        where = []
        if employee_id is not None:
            where.append(ot.OffboardingAssetRecord.employee_id == employee_id)
        if plan_id is not None:
            where.append(ot.OffboardingAssetRecord.plan_id == plan_id)
        if clearance_only:
            where.append(
                ot.OffboardingAssetRecord.status.in_(
                    [AssetStatus.ASSIGNED.value, AssetStatus.MISSING.value]
                )
            )
        with sync_session_scope(self._session_factory) as session:
            total = session.scalar(
                select(func.count()).select_from(ot.OffboardingAssetRecord).where(*where)
            )
            rows = (
                session.execute(
                    select(ot.OffboardingAssetRecord)
                    .where(*where)
                    .order_by(ot.OffboardingAssetRecord.created_at, ot.OffboardingAssetRecord.id)
                    .limit(limit)
                    .offset(offset)
                )
                .scalars()
                .all()
            )
            return [model_from_row(OffboardingAsset, row) for row in rows], int(total or 0)
