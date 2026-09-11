"""Integration tests for the growth API surface."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient) -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Sari Dewi",
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
            "created_by": "hr-admin",
            "job_title": "Finance Staff",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_cycle(client: TestClient, **overrides: object) -> dict:
    payload: dict[str, object] = {
        "name": "2026 H1 Review",
        "period_start": (TODAY - timedelta(days=180)).isoformat(),
        "period_end": TODAY.isoformat(),
        "created_by": "hr-admin",
        "submission_due_on": (TODAY + timedelta(days=2)).isoformat(),
    }
    payload.update(overrides)
    response = client.post("/v1/growth/cycles", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# --- cycle flow ------------------------------------------------------------------


def test_full_review_cycle_flow() -> None:
    with make_client() as client:
        employee = create_employee(client)
        cycle = create_cycle(client, rating_scale_max=5.0)

        assignment = client.post(
            f"/v1/growth/cycles/{cycle['id']}/assignments",
            json={
                "employee_id": employee["id"],
                "reviewer_id": "lead-1",
                "created_by": "hr-admin",
            },
        )
        assert assignment.status_code == 201, assignment.text
        assignment_id = assignment.json()["id"]

        activated = client.post(
            f"/v1/growth/cycles/{cycle['id']}/activate", json={"by": "hr-admin"}
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "active"

        bad_rating = client.post(
            f"/v1/growth/assignments/{assignment_id}/submit",
            json={"by": "lead-1", "ratings": {"delivery": 9.0}},
        )
        assert bad_rating.status_code == 409

        submitted = client.post(
            f"/v1/growth/assignments/{assignment_id}/submit",
            json={
                "by": "lead-1",
                "ratings": {"delivery": 4.5, "collaboration": 4.0},
                "comments": "Consistently solid.",
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["status"] == "submitted"

        reviewing = client.post(
            f"/v1/growth/cycles/{cycle['id']}/reviewing", json={"by": "hr-admin"}
        )
        assert reviewing.status_code == 200
        assert reviewing.json()["status"] == "reviewing"

        draft = client.post(
            "/v1/growth/summaries",
            json={
                "cycle_id": cycle["id"],
                "employee_id": employee["id"],
                "draft_text": "Strong delivery and collaboration.",
                "drafted_by": "agent:feedback_writer",
            },
        )
        assert draft.status_code == 201, draft.text
        assert draft.json()["status"] == "pending_review"
        summary_id = draft.json()["id"]

        agent_finalize = client.post(
            f"/v1/growth/summaries/{summary_id}/finalize",
            json={"by": "agent:feedback_writer", "final_text": "x"},
        )
        assert agent_finalize.status_code == 409

        finalized = client.post(
            f"/v1/growth/summaries/{summary_id}/finalize",
            json={"by": "hr-admin", "final_text": "Final human-edited review text."},
        )
        assert finalized.status_code == 200
        assert finalized.json()["status"] == "finalized"

        closed = client.post(f"/v1/growth/cycles/{cycle['id']}/close", json={"by": "hr-admin"})
        assert closed.status_code == 200
        assert closed.json()["status"] == "completed"


def test_cycle_list_and_status_filter() -> None:
    with make_client() as client:
        create_cycle(client)
        listed = client.get("/v1/growth/cycles", params={"cycle_status": "draft"})

    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_close_cycle_blocked_until_summary_finalized() -> None:
    with make_client() as client:
        employee = create_employee(client)
        cycle = create_cycle(client)
        assignment = client.post(
            f"/v1/growth/cycles/{cycle['id']}/assignments",
            json={
                "employee_id": employee["id"],
                "reviewer_id": "lead-1",
                "created_by": "hr-admin",
            },
        ).json()
        client.post(f"/v1/growth/cycles/{cycle['id']}/activate", json={"by": "hr-admin"})
        client.post(
            f"/v1/growth/assignments/{assignment['id']}/submit",
            json={"by": "lead-1", "ratings": {"delivery": 4.0}},
        )
        client.post(f"/v1/growth/cycles/{cycle['id']}/reviewing", json={"by": "hr-admin"})
        client.post(
            "/v1/growth/summaries",
            json={
                "cycle_id": cycle["id"],
                "employee_id": employee["id"],
                "draft_text": "Draft",
                "drafted_by": "agent:feedback_writer",
            },
        )

        blocked = client.post(f"/v1/growth/cycles/{cycle['id']}/close", json={"by": "hr-admin"})

    assert blocked.status_code == 409
    assert "await human finalization" in blocked.json()["title"]


def test_cancel_cycle_requires_reason() -> None:
    with make_client() as client:
        cycle = create_cycle(client)
        response = client.post(f"/v1/growth/cycles/{cycle['id']}/cancel", json={"by": "hr-admin"})

    assert response.status_code == 422


def test_unknown_cycle_404() -> None:
    with make_client() as client:
        response = client.get("/v1/growth/cycles/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


# --- reminders ---------------------------------------------------------------------


def test_reminders_run_is_deduplicated() -> None:
    with make_client() as client:
        employee = create_employee(client)
        cycle = create_cycle(client, submission_due_on=TODAY.isoformat())
        client.post(
            f"/v1/growth/cycles/{cycle['id']}/assignments",
            json={
                "employee_id": employee["id"],
                "reviewer_id": "lead-1",
                "created_by": "hr-admin",
            },
        )
        client.post(f"/v1/growth/cycles/{cycle['id']}/activate", json={"by": "hr-admin"})

        first = client.post("/v1/growth/reminders/run", json={"as_of": TODAY.isoformat()})
        second = client.post("/v1/growth/reminders/run", json={"as_of": TODAY.isoformat()})
        tasks = client.get("/v1/tasks")

    assert first.status_code == 200
    assert len(first.json()) == 1
    assert second.json() == []
    assert len(tasks.json()) == 1


# --- goals --------------------------------------------------------------------------


def test_goal_lifecycle_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        created = client.post(
            "/v1/growth/goals",
            json={
                "employee_id": employee["id"],
                "title": "Ship onboarding v2",
                "created_by": "hr-admin",
                "due_on": (TODAY + timedelta(days=60)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        goal_id = created.json()["id"]
        assert created.json()["status"] == "draft"

        agent_activate = client.post(
            f"/v1/growth/goals/{goal_id}/activate", json={"by": "agent:planner"}
        )
        assert agent_activate.status_code == 409

        activated = client.post(f"/v1/growth/goals/{goal_id}/activate", json={"by": "hr-admin"})
        assert activated.json()["status"] == "active"

        progress = client.post(
            f"/v1/growth/goals/{goal_id}/progress",
            json={"percent": 40.0, "by": "hr-admin", "note": "beta done"},
        )
        assert progress.status_code == 200
        assert progress.json()["progress_percent"] == 40.0
        assert len(progress.json()["updates"]) == 1

        completed = client.post(
            f"/v1/growth/goals/{goal_id}/complete", json={"by": "hr-admin", "note": "shipped"}
        )
        assert completed.json()["status"] == "completed"
        assert completed.json()["progress_percent"] == 100.0

        listed = client.get("/v1/growth/goals", params={"employee_id": employee["id"]})

    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_goal_cancel_requires_reason() -> None:
    with make_client() as client:
        employee = create_employee(client)
        goal = client.post(
            "/v1/growth/goals",
            json={
                "employee_id": employee["id"],
                "title": "X",
                "created_by": "hr-admin",
            },
        ).json()
        response = client.post(f"/v1/growth/goals/{goal['id']}/cancel", json={"by": "hr-admin"})

    assert response.status_code == 422


def test_overdue_goals_endpoint() -> None:
    with make_client() as client:
        employee = create_employee(client)
        client.post(
            "/v1/growth/goals",
            json={
                "employee_id": employee["id"],
                "title": "Late",
                "created_by": "hr-admin",
                "due_on": (TODAY - timedelta(days=5)).isoformat(),
            },
        )
        overdue = client.get("/v1/growth/goals/overdue")

    assert overdue.status_code == 200
    assert len(overdue.json()) == 1
