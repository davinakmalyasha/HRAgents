"""Integration tests for the leave API surface."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app

TODAY = date.today()
WORK_START = TODAY + timedelta(days=((7 - TODAY.weekday()) % 7 or 7) + 28)


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


def set_annual_policy(client: TestClient) -> None:
    response = client.put(
        "/v1/leave/policies",
        json={
            "leave_type": "annual",
            "name": "Cuti Tahunan",
            "by": "hr-admin",
            "accrual_method": "lump_sum_annual",
            "days_per_year": 12.0,
            "min_service_months": 12,
        },
    )
    assert response.status_code == 200, response.text


def test_policy_set_and_list() -> None:
    with make_client() as client:
        set_annual_policy(client)
        listed = client.get("/v1/leave/policies")

    assert listed.status_code == 200
    assert listed.json()[0]["days_per_year"] == 12.0


def test_balance_view() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        response = client.get(f"/v1/leave/balances/{employee['id']}")

    assert response.status_code == 200
    balance = response.json()[0]
    assert balance["entitled"] == 12.0
    assert balance["available"] == 12.0


def test_full_request_approve_flow() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)

        created = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=4)).isoformat(),
                "requested_by": "sari@example.com",
                "reason": "family event",
            },
        )
        assert created.status_code == 201, created.text
        request = created.json()
        assert request["days"] == 5.0
        assert request["status"] == "pending"

        # Manager approves through the generic approvals API
        decided = client.post(
            f"/v1/approvals/{request['approval_id']}/decide",
            json={"decided_by": "manager-budi", "approve": True, "reason": "ok"},
        )
        assert decided.status_code == 200

        synced = client.post(f"/v1/leave/approvals/{request['approval_id']}/sync")
        assert synced.status_code == 200
        assert synced.json()["status"] == "approved"

        balance = client.get(
            f"/v1/leave/balances/{employee['id']}/annual",
            params={"year": WORK_START.year},
        ).json()
        assert balance["used"] == 5.0
        assert balance["available"] == 7.0


def test_insufficient_balance_conflict() -> None:
    with make_client() as client:
        employee = create_employee(client)
        client.put(
            "/v1/leave/policies",
            json={
                "leave_type": "annual",
                "name": "Cuti Tahunan",
                "by": "hr",
                "accrual_method": "lump_sum_annual",
                "days_per_year": 2.0,
                "min_service_months": 12,
            },
        )
        response = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=4)).isoformat(),
                "requested_by": "sari@example.com",
            },
        )

    assert response.status_code == 409
    assert "insufficient balance" in response.json()["title"]


def test_balance_adjustment() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        response = client.post(
            f"/v1/leave/balances/{employee['id']}/annual/adjust",
            json={"days": 3.0, "by": "hr-admin", "reason": "replacement holiday"},
        )

    assert response.status_code == 200
    assert response.json()["available"] == 15.0


def test_cancel_request_via_api() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        created = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=1)).isoformat(),
                "requested_by": "sari@example.com",
            },
        ).json()

        cancelled = client.post(
            f"/v1/leave/requests/{created['id']}/cancel", json={"by": "sari@example.com"}
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_calendar_endpoint() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        created = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=4)).isoformat(),
                "requested_by": "sari@example.com",
            },
        ).json()
        client.post(
            f"/v1/approvals/{created['approval_id']}/decide",
            json={"decided_by": "manager", "approve": True},
        )
        client.post(f"/v1/leave/approvals/{created['approval_id']}/sync")

        calendar = client.get("/v1/leave/calendar", params={"on_date": WORK_START.isoformat()})

    assert calendar.status_code == 200
    assert len(calendar.json()) == 1


def test_holidays_affect_day_count() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        client.put(
            "/v1/leave/calendar/holidays",
            json={"holidays": [WORK_START.isoformat()], "by": "hr"},
        )
        created = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=4)).isoformat(),
                "requested_by": "sari@example.com",
            },
        )

    assert created.status_code == 201
    assert created.json()["days"] == 4.0  # Monday holiday excluded


def test_pending_listing() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=1)).isoformat(),
                "requested_by": "sari@example.com",
            },
        )
        pending = client.get("/v1/leave", params={"pending_only": True})

    assert pending.status_code == 200
    assert len(pending.json()) == 1
