"""Integration tests for the people API surface (employees, contracts, approvals, tasks)."""

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient, **overrides: object) -> dict:
    payload: dict = {
        "full_name": "Sari Dewi",
        "hire_date": (TODAY - timedelta(days=200)).isoformat(),
        "job_title": "Finance Staff",
    }
    payload.update(overrides)
    response = client.post("/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_get_employee() -> None:
    with make_client() as client:
        created = create_employee(client)
        fetched = client.get(f"/v1/employees/{created['id']}")

    assert fetched.status_code == 200
    assert fetched.json()["full_name"] == "Sari Dewi"
    assert fetched.json()["status"] == "active"


def test_list_employees_filtered_by_status() -> None:
    with make_client() as client:
        create_employee(client, full_name="Active One")
        create_employee(
            client,
            full_name="Future One",
            hire_date=(TODAY + timedelta(days=14)).isoformat(),
        )
        response = client.get("/v1/employees", params={"status": "onboarding"})

    assert response.status_code == 200
    names = [item["full_name"] for item in response.json()]
    assert names == ["Future One"]


def test_employee_lifecycle_transition() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            f"/v1/employees/{employee['id']}/transition",
            json={"target": "notice_period"},
        )
        invalid = client.post(
            f"/v1/employees/{employee['id']}/transition",
            json={"target": "probation"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "notice_period"
    assert invalid.status_code == 409


def test_add_document_and_list_contracts() -> None:
    with make_client() as client:
        employee = create_employee(client)
        document = client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": f"employees/{employee['id']}/ktp.pdf",
                "sha256": "a" * 64,
            },
        )
        contracts = client.get(f"/v1/employees/{employee['id']}/contracts")

    assert document.status_code == 201
    assert document.json()["kind"] == "ktp"
    assert contracts.status_code == 200
    assert contracts.json() == []


def test_employee_documents_are_listed_per_employee() -> None:
    with make_client() as client:
        employee = create_employee(client)
        other = create_employee(client, full_name="Rina Wulandari")
        for kind in ("ktp", "npwp"):
            created = client.post(
                f"/v1/employees/{employee['id']}/documents",
                json={
                    "kind": kind,
                    "storage_key": f"employees/{employee['id']}/{kind}.pdf",
                    "sha256": "a" * 64,
                },
            )
            assert created.status_code == 201, created.text
        client.post(
            f"/v1/employees/{other['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": f"employees/{other['id']}/ktp.pdf",
                "sha256": "b" * 64,
            },
        )

        mine = client.get(f"/v1/employees/{employee['id']}/documents")
        unknown = client.get(f"/v1/employees/{uuid4()}/documents")

    assert mine.status_code == 200
    kinds = sorted(document["kind"] for document in mine.json())
    assert kinds == ["ktp", "npwp"]
    assert all(document["employee_id"] == employee["id"] for document in mine.json())
    assert unknown.status_code == 404


def test_document_vault_filters_and_expiry_windows() -> None:
    with make_client() as client:
        employee = create_employee(client)
        soon = client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": "employees/ktp.pdf",
                "sha256": "a" * 64,
                "expires_on": (TODAY + timedelta(days=10)).isoformat(),
            },
        ).json()
        client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "npwp",
                "storage_key": "employees/npwp.pdf",
                "sha256": "b" * 64,
                "expires_on": (TODAY + timedelta(days=200)).isoformat(),
            },
        )
        client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "bank_account",
                "storage_key": "employees/bank.pdf",
                "sha256": "c" * 64,
            },
        )

        vault = client.get("/v1/documents")
        expiring = client.get("/v1/documents", params={"expiring_within_days": 30})
        scoped = client.get("/v1/documents", params={"employee_id": employee["id"]})
        other = client.get("/v1/documents", params={"employee_id": str(uuid4())})

    assert vault.status_code == 200
    # Soonest expiry first, and the no-expiry document last.
    assert [document["kind"] for document in vault.json()] == ["ktp", "npwp", "bank_account"]
    assert soon["days_to_expiry"] == 10
    assert [document["kind"] for document in expiring.json()] == ["ktp"]
    assert len(scoped.json()) == 3
    assert other.json() == []


def test_document_verification_refuses_a_caller_supplied_actor() -> None:
    """Verifying a legal document cannot be attributed to a chosen name.

    The actor is the authenticated principal, so ``verified_by`` is not merely
    ignored -- it is refused, and a caller who believed they had overridden the
    attribution finds out. The named-human gate that used to answer 403 here now
    lives in the service, where an agent actor can exist; it is covered in
    tests/test_named_human_gates.py.
    """
    with make_client() as client:
        employee = create_employee(client)
        document = client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": "employees/ktp.pdf",
                "sha256": "a" * 64,
            },
        ).json()

        agent = client.post(
            f"/v1/documents/{document['id']}/verify",
            json={"verified_by": "agent:onboarding_coordinator"},
        )
        verified = client.post(
            f"/v1/documents/{document['id']}/verify",
            json={"verified": True},
        )
        rejected = client.post(
            f"/v1/documents/{document['id']}/verify",
            json={"verified": False},
        )
        unknown = client.post(
            f"/v1/documents/{uuid4()}/verify",
            json={"verified": True},
        )
        filtered = client.get("/v1/documents", params={"status": "failed"})

    assert document["status"] == "claimed"
    assert agent.status_code == 422
    assert any(error["loc"][-1] == "verified_by" for error in agent.json()["detail"])
    assert verified.status_code == 200
    assert verified.json()["status"] == "verified"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "failed"
    assert unknown.status_code == 404
    assert [document["id"] for document in filtered.json()] == [document["id"]]


def test_org_units_report_headcount_and_reject_unknown_parents() -> None:
    with make_client() as client:
        root = client.post("/v1/org-units", json={"name": "Engineering"}).json()
        child = client.post(
            "/v1/org-units",
            json={
                "name": "Platform",
                "parent_id": root["id"],
                "cost_center": "CC-1",
            },
        ).json()
        create_employee(client, full_name="Budi Santoso")
        listed = client.get("/v1/org-units")
        orphan = client.post(
            "/v1/org-units",
            json={"name": "Ghost", "parent_id": str(uuid4())},
        )

    assert child["parent_id"] == root["id"]
    assert listed.status_code == 200
    assert [unit["name"] for unit in listed.json()] == ["Engineering", "Platform"]
    assert all(unit["headcount"] == 0 for unit in listed.json())
    assert orphan.status_code == 409


def test_contract_lifecycle_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        created = client.post(
            "/v1/contracts",
            json={
                "employee_id": employee["id"],
                "contract_type": "pkwt",
                "start_date": (TODAY - timedelta(days=330)).isoformat(),
                "end_date": (TODAY + timedelta(days=30)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        contract_id = created.json()["id"]

        activated = client.post(f"/v1/contracts/{contract_id}/activate", json={})
        expiring = client.get("/v1/contracts", params={"expiring_within_days": 60})

    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert expiring.status_code == 200
    assert any(item["id"] == contract_id for item in expiring.json())


def test_pkwt_without_end_date_rejected() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            "/v1/contracts",
            json={
                "employee_id": employee["id"],
                "contract_type": "pkwt",
                "start_date": TODAY.isoformat(),
            },
        )
    assert response.status_code == 409  # model validation surfaced as conflict


def test_approval_flow_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/approvals",
            json={
                "subject": "leave_request",
                "subject_id": "leave-1",
                "title": "Annual leave 3 days",
                "assignee_role": "manager",
                "urgency": "high",
            },
        )
        assert created.status_code == 201, created.text
        approval_id = created.json()["id"]

        queue_response = client.get("/v1/approvals", params={"role": "manager"})
        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"approve": True, "reason": "ok"},
        )

    assert queue_response.status_code == 200
    assert any(item["id"] == approval_id for item in queue_response.json())
    assert decided.status_code == 200
    assert decided.json()["action"] == "approved"
    assert decided.json()["request"]["status"] == "approved"


def test_approval_request_and_decision_take_their_actor_from_the_key() -> None:
    """Neither creating nor deciding an approval can name an actor in the body.

    The old test asserted a 409 "named human" for a body carrying
    ``decided_by="agent:policy_assistant"``. Unreachable over HTTP now: a request
    cannot name an actor at all, so both attempts are refused at the boundary
    with a 422 that names the field. ``ApprovalEngine`` still refuses a
    non-human actor, covered in ``tests/test_named_human_gates.py``.
    """
    with make_client() as client:
        create_refused = client.post(
            "/v1/approvals",
            json={
                "subject": "candidate_rejection",
                "subject_id": "cand-1",
                "title": "Rejection sign-off",
                "assignee_role": "engineering_lead",
                "requested_by": "policy_engine",
            },
        )
        created = client.post(
            "/v1/approvals",
            json={
                "subject": "candidate_rejection",
                "subject_id": "cand-1",
                "title": "Rejection sign-off",
                "assignee_role": "engineering_lead",
            },
        )
        approval_id = created.json()["id"]
        decide_refused = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"approve": True, "decided_by": "agent:policy_assistant"},
        )
        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"approve": True},
        )

    assert create_refused.status_code == 422
    assert any(error["loc"][-1] == "requested_by" for error in create_refused.json()["detail"])
    assert created.json()["requested_by"] == "local-dev"
    assert created.json()["requested_by_agent"] is False
    assert decide_refused.status_code == 422
    assert any(error["loc"][-1] == "decided_by" for error in decide_refused.json()["detail"])
    assert decided.status_code == 200
    assert decided.json()["action"] == "approved"


def test_tasks_flow_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/tasks",
            json={
                "title": "Chase missing NPWP",
                "assignee_role": "hr_admin",
                "due_on": (TODAY - timedelta(days=1)).isoformat(),
                "priority": "high",
            },
        )
        assert created.status_code == 201
        task_id = created.json()["id"]

        overdue = client.get("/v1/tasks", params={"overdue_only": True})
        completed = client.post(f"/v1/tasks/{task_id}/complete", json={})
        after = client.get("/v1/tasks")

    assert any(item["id"] == task_id for item in overdue.json())
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"
    assert all(item["id"] != task_id for item in after.json())


def test_rate_table_unverified_gate_via_api() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/rate-tables",
            json={"kind": "bpjs_kesehatan", "name": "BPJS Kesehatan"},
        )
        unverified = client.get("/v1/rate-tables/unverified")

    assert created.status_code == 201
    assert created.json()["verified"] is False
    assert created.json()["usable"] is False
    assert any(item["id"] == created.json()["id"] for item in unverified.json())


def test_unknown_employee_returns_404() -> None:
    with make_client() as client:
        response = client.get(f"/v1/employees/{uuid4()}")
    assert response.status_code == 404
