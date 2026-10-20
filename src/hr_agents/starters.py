"""Operator starter content: checklists and empty rate-table shells.

Templates are process choices, so seeding them is a shortcut, not a policy
decision. Statutory rates are different: the hard rule is that a named human
enters and certifies every number, so a rate table is created **empty and
unverified**. Payroll already flags an unusable table, which turns the fresh
install into a precise checklist instead of a silent default.

Idempotent by content identity: a template that already exists by name, and a
rate table of a kind that already exists, are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hr_agents.identity import ActorRef
from hr_agents.models import (
    DocumentKind,
    OffboardingStepKind,
    RateTableKind,
    StepKind,
)
from hr_agents.models.offboarding import OffboardingTemplateStep
from hr_agents.models.onboarding import TemplateStep
from hr_agents.services.payroll import REQUIRED_TABLES
from hr_agents.services.people import PeopleServices

STARTER_ONBOARDING_NAME = "New hire starter"
STARTER_OFFBOARDING_NAME = "Resignation checklist"

STARTER_ONBOARDING_STEPS: tuple[TemplateStep, ...] = (
    TemplateStep(
        key="collect_identity_document",
        title="Collect the identity document",
        kind=StepKind.DOCUMENT,
        document_kind=DocumentKind.KTP,
        due_days_after_hire=3,
    ),
    TemplateStep(
        key="sign_contract",
        title="Sign the employment contract",
        kind=StepKind.CONTRACT,
        due_days_after_hire=1,
    ),
    TemplateStep(
        key="set_up_accounts",
        title="Set up email and tools",
        kind=StepKind.ACCOUNT_SETUP,
        due_days_after_hire=1,
    ),
    TemplateStep(
        key="orientation",
        title="First-week orientation",
        kind=StepKind.ORIENTATION,
        due_days_after_hire=7,
    ),
    TemplateStep(
        key="confirm_probation_review",
        title="Confirm the probation review date",
        kind=StepKind.CONFIRMATION,
        due_days_after_hire=90,
    ),
)

STARTER_OFFBOARDING_STEPS: tuple[OffboardingTemplateStep, ...] = (
    OffboardingTemplateStep(
        key="handover",
        title="Hand over responsibilities",
        kind=OffboardingStepKind.HANDOVER,
        due_days_before_last_day=5,
    ),
    OffboardingTemplateStep(
        key="return_assets",
        title="Return company assets",
        kind=OffboardingStepKind.ASSET_RETURN,
        due_days_before_last_day=1,
    ),
    OffboardingTemplateStep(
        key="close_accounts",
        title="Close accounts and access",
        kind=OffboardingStepKind.ACCOUNT_CLOSURE,
        due_days_before_last_day=0,
    ),
    OffboardingTemplateStep(
        key="exit_interview",
        title="Run the exit interview",
        kind=OffboardingStepKind.EXIT_INTERVIEW,
        due_days_before_last_day=3,
    ),
    OffboardingTemplateStep(
        key="final_pay",
        title="Prepare the final settlement",
        kind=OffboardingStepKind.FINAL_PAY,
        due_days_before_last_day=0,
        requires_human_signoff=True,
    ),
)

# Every table payroll would otherwise block on, plus the PPh 21 TER brackets.
# The shells carry no values on purpose: `verified` stays false until a person
# enters the numbers and records where they came from.
STARTER_RATE_TABLES: tuple[RateTableKind, ...] = (*REQUIRED_TABLES, RateTableKind.PPH21_TER)


@dataclass
class StarterReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.created)


def seed_starters(
    people: PeopleServices,
    *,
    actor: ActorRef,
    jurisdiction: str = "ID",
) -> StarterReport:
    """Create the starter templates and rate-table shells that are missing."""
    report = StarterReport()

    existing_onboarding = {
        template.name for template in people.onboarding.list_templates(active_only=False)
    }
    if STARTER_ONBOARDING_NAME in existing_onboarding:
        report.skipped.append(f"onboarding_template:{STARTER_ONBOARDING_NAME}")
    else:
        people.onboarding.create_template(
            name=STARTER_ONBOARDING_NAME,
            description="Default first-week checklist; edit the steps to match your process.",
            steps=list(STARTER_ONBOARDING_STEPS),
            actor=actor,
        )
        report.created.append(f"onboarding_template:{STARTER_ONBOARDING_NAME}")

    existing_offboarding = {
        template.name for template in people.offboarding.list_templates(active_only=False)
    }
    if STARTER_OFFBOARDING_NAME in existing_offboarding:
        report.skipped.append(f"offboarding_template:{STARTER_OFFBOARDING_NAME}")
    else:
        people.offboarding.create_template(
            name=STARTER_OFFBOARDING_NAME,
            description="Default exit checklist; edit the steps to match your process.",
            steps=list(STARTER_OFFBOARDING_STEPS),
            actor=actor,
        )
        report.created.append(f"offboarding_template:{STARTER_OFFBOARDING_NAME}")

    existing_kinds = {table.kind for table in people.rate_tables.list_all()}
    for kind in STARTER_RATE_TABLES:
        if kind in existing_kinds:
            report.skipped.append(f"rate_table:{kind.value}")
            continue
        people.rate_tables.create(
            kind=kind,
            name=f"{kind.value} (enter and verify)",
            actor=actor,
            jurisdiction=jurisdiction,
        )
        report.created.append(f"rate_table:{kind.value}")
        existing_kinds.add(kind)

    return report
