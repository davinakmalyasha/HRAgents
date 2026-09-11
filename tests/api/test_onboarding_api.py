"""Integration tests for the onboarding API surface."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient, *, job_title: str = "Backend Engineer") -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Budi Santoso",
            "hire_date": TODAY.isoformat(),
            "created_by": "hr-admin",
            "job_title": job_title,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_template(client: TestClient) -> dict:
    response = client.post(
        "/v1/onboarding/templates",
        json={
            "name": "Engineering Starter",
            "created_by": "hr-admin",
            "applies_to_roles": ["engineer"],
            "steps": [
                {
                    "key": "collect_ktp",
                    "title": "Collect KTP",
                    "kind": "document",
                    "document_kind": "ktp",
                    "due_days_after_hire": 3,
                },
                {
                    "key": "sign_contract",
                    "title": "Sign contract",
                    "kind": "contract",
                    "requires_human_signoff": True,
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_onboarding_flow_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)

        started = client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        )
        assert started.status_code == 201, started.text
        plan = started.json()
        assert len(plan["steps"]) == 2
        assert plan["progress"] == 0.0
        assert set(plan["blockers"]) == {"collect_ktp", "sign_contract"}

        completed = client.post(
            f"/v1/onboarding/plans/{plan['id']}/steps/sign_contract/complete",
            json={"by": "hr-admin"},
        )
        assert completed.status_code == 200
        assert completed.json()["progress"] == 0.5


def test_agent_step_completion_rejected_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)
        started = client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        )
        plan = started.json()

        response = client.post(
            f"/v1/onboarding/plans/{plan['id']}/steps/sign_contract/complete",
            json={"by": "agent:onboarding_coordinator"},
        )

    assert response.status_code == 409
    assert "completed by humans" in response.json()["title"]


def test_document_link_and_status_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)
        plan = client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        ).json()

        document = client.post(
            f"/v1/employees/{employee['id']}/documents",
            json={
                "kind": "ktp",
                "storage_key": "employees/ktp.pdf",
                "sha256": "a" * 64,
                "uploaded_by": "hr-admin",
            },
        ).json()

        linked = client.post(
            f"/v1/onboarding/plans/{plan['id']}/steps/collect_ktp/link-document",
            json={"document_id": document["id"], "linked_by": "hr-admin"},
        )
        status = client.get(f"/v1/onboarding/plans/{plan['id']}/document-status")

    assert linked.status_code == 200
    assert status.status_code == 200
    assert status.json() == {"collect_ktp": "pending_validation"}


def test_waive_requires_reason_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)
        plan = client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        ).json()

        response = client.post(
            f"/v1/onboarding/plans/{plan['id']}/steps/collect_ktp/waive",
            json={"by": "hr-admin", "reason": ""},
        )

    assert response.status_code == 422  # schema-level min_length


def test_start_plan_without_matching_template_conflicts() -> None:
    with make_client() as client:
        employee = create_employee(client, job_title="Warehouse Operator")
        response = client.post(
            "/v1/onboarding/plans",
            json={"employee_id": employee["id"], "created_by": "hr-admin"},
        )

    assert response.status_code == 409
    assert "no onboarding template" in response.json()["title"]


def test_tasks_created_for_onboarding_steps() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)
        client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        )
        tasks = client.get("/v1/tasks").json()

    titles = [task["title"] for task in tasks]
    assert any(title == "[Onboarding] Collect KTP" for title in titles)
    assert any(task["source"] == "agent" for task in tasks)


def test_templates_listing() -> None:
    with make_client() as client:
        create_template(client)
        response = client.get("/v1/onboarding/templates")

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["step_count"] == 2


def test_onboarding_due_date_math() -> None:
    with make_client() as client:
        employee = create_employee(client)
        template = create_template(client)
        plan = client.post(
            "/v1/onboarding/plans",
            json={
                "employee_id": employee["id"],
                "created_by": "hr-admin",
                "template_id": template["id"],
            },
        ).json()

    ktp_step = next(step for step in plan["steps"] if step["key"] == "collect_ktp")
    assert ktp_step["due_on"] == (TODAY + timedelta(days=3)).isoformat()
