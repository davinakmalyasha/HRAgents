"""Integration tests for the offboarding API surface."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()
LAST_DAY = TODAY + timedelta(days=30)


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient) -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Rudi Hartono",
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
            "created_by": "hr-admin",
            "job_title": "Engineering Lead",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def install_default_template(client: TestClient) -> dict:
    default = client.get("/v1/offboarding/templates/default")
    assert default.status_code == 200
    body = default.json()
    template = client.post(
        "/v1/offboarding/templates",
        json={
            "name": body["name"],
            "description": body["description"],
            "steps": body["steps"],
            "applies_to_reasons": body["applies_to_reasons"],
            "applies_to_roles": body["applies_to_roles"],
            "created_by": "hr-admin",
        },
    )
    assert template.status_code == 201, template.text
    return template.json()


def start_plan(client: TestClient, employee_id: str) -> dict:
    response = client.post(
        "/v1/offboarding/plans",
        json={
            "employee_id": employee_id,
            "reason": "resignation",
            "last_working_day": LAST_DAY.isoformat(),
            "created_by": "hr-admin",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- templates --------------------------------------------------------------------


def test_default_template_endpoint_shape() -> None:
    with make_client() as client:
        response = client.get("/v1/offboarding/templates/default")

    assert response.status_code == 200
    body = response.json()
    assert len(body["steps"]) == 6
    assert body["steps"][0]["key"] == "handover"
    assert body["steps"][-1]["requires_human_signoff"] is True


def test_install_and_list_templates() -> None:
    with make_client() as client:
        install_default_template(client)
        listed = client.get("/v1/offboarding/templates")
        default_only = client.get("/v1/offboarding/templates", params={})

    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert default_only.json()[0]["name"] == "Resignation — starter"


# --- full exit flow -----------------------------------------------------------------


def test_full_exit_flow_with_assets_and_final_pay() -> None:
    with make_client() as client:
        employee = create_employee(client)
        install_default_template(client)
        plan = start_plan(client, employee["id"])
        plan_id = plan["id"]

        # Employee moved into notice period by starting the plan.
        refreshed = client.get(f"/v1/employees/{employee['id']}")
        assert refreshed.json()["status"] == "notice_period"

        asset = client.post(
            "/v1/offboarding/assets",
            json={
                "employee_id": employee["id"],
                "name": "MacBook Pro",
                "created_by": "hr-admin",
                "asset_code": "MB-001",
                "plan_id": plan_id,
            },
        )
        assert asset.status_code == 201, asset.text
        asset_id = asset.json()["id"]
        assert asset.json()["blocks_clearance"] is True

        # Complete all steps as a human.
        for step in plan["steps"]:
            done = client.post(
                f"/v1/offboarding/plans/{plan_id}/steps/{step['key']}/complete",
                json={"by": "hr-admin"},
            )
            assert done.status_code == 200, done.text

        # Agent tries to complete a step, is refused.
        agent_step = client.post(
            f"/v1/offboarding/plans/{plan_id}/steps/handover/complete",
            json={"by": "agent:offboarding_coordinator"},
        )
        assert agent_step.status_code == 409

        # Final pay coordination creates a FINAL run.
        final_pay = client.post(
            f"/v1/offboarding/plans/{plan_id}/final-pay", json={"by": "hr-admin"}
        )
        assert final_pay.status_code == 200, final_pay.text
        run_id = final_pay.json()["final_pay_run_id"]
        run = client.get(f"/v1/payroll/runs/{run_id}")
        assert run.json()["kind"] == "final"
        assert run.json()["status"] == "draft"

        # Completion is blocked while the asset is out.
        blocked = client.post(f"/v1/offboarding/plans/{plan_id}/complete", json={"by": "hr-admin"})
        assert blocked.status_code == 409
        assert "assets not cleared" in blocked.json()["title"]

        returned = client.post(
            f"/v1/offboarding/assets/{asset_id}/return",
            json={"by": "hr-admin", "note": "returned at office"},
        )
        assert returned.status_code == 200
        assert returned.json()["blocks_clearance"] is False

        finalized = client.post(
            f"/v1/offboarding/plans/{plan_id}/finalize-employee", json={"by": "hr-admin"}
        )
        assert finalized.status_code == 200, finalized.text
        assert finalized.json()["is_complete"] is True

        final_employee = client.get(f"/v1/employees/{employee['id']}")
        assert final_employee.json()["status"] == "offboarded"
        assert final_employee.json()["offboarded_on"] == TODAY.isoformat()


def test_write_off_missing_asset_clears_clearance() -> None:
    with make_client() as client:
        employee = create_employee(client)
        install_default_template(client)
        start_plan(client, employee["id"])
        asset = client.post(
            "/v1/offboarding/assets",
            json={"employee_id": employee["id"], "name": "Phone", "created_by": "hr-admin"},
        ).json()

        missing = client.post(
            f"/v1/offboarding/assets/{asset['id']}/missing",
            json={"by": "hr-admin", "note": "not in locker"},
        )
        assert missing.status_code == 200
        assert missing.json()["status"] == "missing"

        clearance = client.get(f"/v1/offboarding/employees/{employee['id']}/clearance")
        assert len(clearance.json()) == 1

        write_off = client.post(
            f"/v1/offboarding/assets/{asset['id']}/write-off",
            json={"by": "hr-admin", "reason": "police report filed"},
        )
        assert write_off.status_code == 200
        assert write_off.json()["status"] == "written_off"

        clearance_after = client.get(f"/v1/offboarding/employees/{employee['id']}/clearance")
        assert clearance_after.json() == []


def test_waive_step_requires_reason() -> None:
    with make_client() as client:
        employee = create_employee(client)
        install_default_template(client)
        plan = start_plan(client, employee["id"])

        response = client.post(
            f"/v1/offboarding/plans/{plan['id']}/steps/handover/waive",
            json={"by": "hr-admin"},
        )
        assert response.status_code == 422

        waived = client.post(
            f"/v1/offboarding/plans/{plan['id']}/steps/handover/waive",
            json={"by": "hr-admin", "reason": "no active projects"},
        )
        assert waived.status_code == 200
        handover = next(step for step in waived.json()["steps"] if step["key"] == "handover")
        assert handover["status"] == "waived"


def test_handover_note_and_exit_interview_scheduling() -> None:
    with make_client() as client:
        employee = create_employee(client)
        install_default_template(client)
        plan = start_plan(client, employee["id"])

        note = client.post(
            f"/v1/offboarding/plans/{plan['id']}/handover",
            json={"content": "Prod credentials in Vault path x.", "authored_by": "rudi"},
        )
        assert note.status_code == 200
        assert len(note.json()["handover_notes"]) == 1

        scheduled = client.post(
            f"/v1/offboarding/plans/{plan['id']}/exit-interview",
            json={"scheduled_for": f"{LAST_DAY.isoformat()}T09:00:00+07:00", "by": "hr-admin"},
        )
        assert scheduled.status_code == 200, scheduled.text
        interview = next(
            step for step in scheduled.json()["steps"] if step["key"] == "exit_interview"
        )
        assert interview["scheduled_for"] is not None
        assert interview["status"] == "in_progress"


def test_plan_requires_template() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            "/v1/offboarding/plans",
            json={
                "employee_id": employee["id"],
                "reason": "resignation",
                "last_working_day": LAST_DAY.isoformat(),
                "created_by": "hr-admin",
            },
        )

    assert response.status_code == 409
    assert "no offboarding template" in response.json()["title"]


def test_unknown_plan_404() -> None:
    with make_client() as client:
        response = client.get("/v1/offboarding/plans/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


def test_agent_cannot_register_asset() -> None:
    with make_client() as client:
        employee = create_employee(client)
        response = client.post(
            "/v1/offboarding/assets",
            json={
                "employee_id": employee["id"],
                "name": "Laptop",
                "created_by": "agent:offboarding_coordinator",
            },
        )

    assert response.status_code == 409
