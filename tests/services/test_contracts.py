from datetime import date, timedelta
from uuid import UUID, uuid4

import pytest

from hr_agents.models import Contract, ContractStatus, ContractType, TaskSource
from hr_agents.services import (
    ContractError,
    ContractService,
    ContractStore,
    TaskEngine,
    TaskStore,
)
from hr_agents.services.audit import AuditChain

TODAY = date.today()


@pytest.fixture
def service() -> ContractService:
    return ContractService(
        ContractStore(),
        audit=AuditChain(),
        tasks=TaskEngine(TaskStore(), audit=AuditChain()),
        warning_days=60,
    )


def create_pkwt(
    service: ContractService,
    *,
    days_until_end: int,
    employee_id: UUID | None = None,
) -> Contract:
    return service.create(
        employee_id=employee_id if employee_id is not None else uuid4(),
        contract_type=ContractType.PKWT,
        start_date=TODAY - timedelta(days=365),
        created_by="hr-admin",
        end_date=TODAY + timedelta(days=days_until_end),
    )


# --- creation & activation ---------------------------------------------------


def test_pkwt_requires_end_date() -> None:
    with pytest.raises(ValueError, match="end_date"):
        ContractStore()  # no-op guard for import clarity
        from hr_agents.models import Contract

        Contract(
            employee_id=uuid4(),
            contract_type=ContractType.PKWT,
            start_date=TODAY,
        )


def test_pkwtt_open_ended_allowed() -> None:
    from hr_agents.models import Contract

    contract = Contract(
        employee_id=uuid4(),
        contract_type=ContractType.PKWTT,
        start_date=TODAY,
        probation_end_date=TODAY + timedelta(days=90),
    )
    assert contract.is_open_ended


def test_probation_rejected_for_pkwt() -> None:
    from hr_agents.models import Contract

    with pytest.raises(ValueError, match="probation"):
        Contract(
            employee_id=uuid4(),
            contract_type=ContractType.PKWT,
            start_date=TODAY,
            end_date=TODAY + timedelta(days=365),
            probation_end_date=TODAY + timedelta(days=90),
        )


def test_activate_flow(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=200)
    assert contract.status is ContractStatus.DRAFT

    activated = service.activate(contract.id, by="hr-admin")
    assert activated.status is ContractStatus.ACTIVE
    assert activated.signed_on == TODAY


def test_activate_twice_rejected(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=200)
    service.activate(contract.id, by="hr-admin")
    with pytest.raises(ContractError, match="cannot activate"):
        service.activate(contract.id, by="hr-admin")


# --- status maintenance ------------------------------------------------------


def test_refresh_marks_expiring_within_window(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=30)
    service.activate(contract.id, by="hr-admin")

    refreshed = service.refresh_status(contract.id)
    assert refreshed.status is ContractStatus.EXPIRING


def test_refresh_marks_expired_past_end(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=1)
    service.activate(contract.id, by="hr-admin")

    refreshed = service.refresh_status(contract.id, as_of=TODAY + timedelta(days=5))
    assert refreshed.status is ContractStatus.EXPIRED


def test_refresh_returns_to_active_when_extended(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=30)
    service.activate(contract.id, by="hr-admin")
    service.refresh_status(contract.id)

    extended = service._store.get(contract.id)
    assert extended is not None
    service._store.save(extended.model_copy(update={"end_date": TODAY + timedelta(days=300)}))
    refreshed = service.refresh_status(contract.id)
    assert refreshed.status is ContractStatus.ACTIVE


def test_compensation_flag_set_near_pkwt_completion(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=20)
    service.activate(contract.id, by="hr-admin")

    refreshed = service.refresh_status(contract.id)
    assert refreshed.compensation_due is True


def test_compensation_flag_not_set_for_pkwtt() -> None:
    from hr_agents.models import Contract

    contract = Contract(
        employee_id=uuid4(),
        contract_type=ContractType.PKWTT,
        start_date=TODAY - timedelta(days=365),
        status=ContractStatus.ACTIVE,
    )
    assert contract.compensation_due is False


def test_refresh_all(service: ContractService) -> None:
    create_pkwt(service, days_until_end=30)
    create_pkwt(service, days_until_end=300)
    results = service.refresh_all()
    assert len(results) == 2


def test_terminate_records_reason(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=200)
    terminated = service.terminate(contract.id, by="hr-admin", reason="resignation")
    assert terminated.status is ContractStatus.TERMINATED
    assert "resignation" in (terminated.notes or "")


# --- expiry math -------------------------------------------------------------


def test_months_of_service_across_year_boundary(service: ContractService) -> None:
    from hr_agents.models import Contract

    contract = Contract(
        employee_id=uuid4(),
        contract_type=ContractType.PKWTT,
        start_date=date(2024, 11, 15),
    )
    assert contract.months_of_service(as_of=date(2025, 2, 14)) == 2
    assert contract.months_of_service(as_of=date(2025, 2, 15)) == 3


def test_days_until_expiry_and_expired(service: ContractService) -> None:
    contract = create_pkwt(service, days_until_end=10)
    assert contract.days_until_expiry() == 10
    assert contract.expired() is False
    assert contract.expired(as_of=TODAY + timedelta(days=11)) is True


# --- tasks -------------------------------------------------------------------


def test_expiry_tasks_created_once(service: ContractService) -> None:
    create_pkwt(service, days_until_end=15)
    create_pkwt(service, days_until_end=45)

    created = service.create_expiry_tasks()
    assert len(created) == 2
    assert all(task.source is TaskSource.AGENT for task in created)

    again = service.create_expiry_tasks()
    assert again == []


def test_no_tasks_when_nothing_expiring(service: ContractService) -> None:
    create_pkwt(service, days_until_end=300)
    assert service.create_expiry_tasks() == []


def test_expiry_tasks_need_task_engine() -> None:
    service = ContractService(ContractStore(), audit=AuditChain())
    create_pkwt(service, days_until_end=10)
    with pytest.raises(ContractError, match="task engine"):
        service.create_expiry_tasks()


# --- queries -----------------------------------------------------------------


def test_active_for_employee(service: ContractService) -> None:
    employee_id = uuid4()
    old = create_pkwt(service, days_until_end=300, employee_id=employee_id)
    service.activate(old.id, by="hr")
    service.terminate(old.id, by="hr", reason="replaced")

    new = create_pkwt(service, days_until_end=300, employee_id=employee_id)
    service.activate(new.id, by="hr")

    active = service.active_for_employee(employee_id)
    assert active is not None
    assert active.id == new.id


def test_unknown_contract_raises(service: ContractService) -> None:
    with pytest.raises(ContractError, match="unknown contract"):
        service.get(uuid4())
