"""Integration tests for the leave API surface."""

from datetime import timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.models import business_today

TODAY = business_today()
WORK_START = TODAY + timedelta(days=((7 - TODAY.weekday()) % 7 or 7) + 28)


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient, full_name: str = "Sari Dewi") -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": full_name,
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
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
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["days_per_year"] == 12.0


def test_balance_view() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        response = client.get(f"/v1/leave/balances/{employee['id']}")

    assert response.status_code == 200
    balance = response.json()["items"][0]
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
            json={"approve": True, "reason": "ok"},
        )
        assert decided.status_code == 200

        synced = client.post(f"/v1/leave/approvals/{request['approval_id']}/sync", json={})
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
            json={"days": 3.0, "reason": "replacement holiday"},
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
            },
        ).json()

        cancelled = client.post(
            f"/v1/leave/requests/{created['id']}/cancel",
            json={"reason": "Flights were rebooked to next month."},
        )

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_cancel_without_a_reason_is_refused() -> None:
    """The endpoint always accepted a reason and then ignored it.

    Cancelling somebody else's leave is as consequential as filing it, so the record has
    to say why. A blank reason is a refusal rather than a silent discard.
    """
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
            },
        ).json()

        refused = client.post(f"/v1/leave/requests/{created['id']}/cancel", json={})
        still_pending = client.get(f"/v1/leave/requests/{created['id']}")

    assert refused.status_code == 409
    assert "requires a reason" in refused.json()["detail"]
    assert still_pending.json()["status"] == "pending"


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
            },
        ).json()
        client.post(
            f"/v1/approvals/{created['approval_id']}/decide",
            json={"approve": True},
        )
        client.post(f"/v1/leave/approvals/{created['approval_id']}/sync", json={})

        calendar = client.get("/v1/leave/calendar", params={"on_date": WORK_START.isoformat()})

    assert calendar.status_code == 200
    assert calendar.json()["total"] == 1
    assert len(calendar.json()["items"]) == 1


def test_holidays_affect_day_count() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        client.put(
            "/v1/leave/calendar/holidays",
            json={"holidays": [WORK_START.isoformat()]},
        )
        created = client.post(
            "/v1/leave",
            json={
                "employee_id": employee["id"],
                "leave_type": "annual",
                "start_date": WORK_START.isoformat(),
                "end_date": (WORK_START + timedelta(days=4)).isoformat(),
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
            },
        )
        pending = client.get("/v1/leave", params={"pending_only": True})

    assert pending.status_code == 200
    assert pending.json()["total"] == 1
    assert len(pending.json()["items"]) == 1


def test_request_listing_pages_with_a_stable_total() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        for week in range(3):
            start = WORK_START + timedelta(days=week * 7)
            created = client.post(
                "/v1/leave",
                json={
                    "employee_id": employee["id"],
                    "leave_type": "annual",
                    "start_date": start.isoformat(),
                    "end_date": (start + timedelta(days=1)).isoformat(),
                },
            )
            assert created.status_code == 201, created.text

        whole = client.get("/v1/leave", params={"pending_only": True})
        first = client.get("/v1/leave", params={"pending_only": True, "limit": 2, "offset": 0})
        second = client.get("/v1/leave", params={"pending_only": True, "limit": 2, "offset": 2})
        past = client.get("/v1/leave", params={"pending_only": True, "limit": 2, "offset": 10})

    assert whole.status_code == 200
    assert whole.json()["total"] == 3
    assert whole.json()["limit"] == 100
    assert first.status_code == second.status_code == past.status_code == 200
    assert first.json()["total"] == second.json()["total"] == past.json()["total"] == 3
    assert first.json()["offset"] == 0
    assert second.json()["offset"] == 2
    assert len(first.json()["items"]) == 2
    assert len(second.json()["items"]) == 1
    assert past.json()["items"] == []
    paged_ids = [item["id"] for item in first.json()["items"] + second.json()["items"]]
    assert paged_ids == [item["id"] for item in whole.json()["items"]]


def test_balance_listing_pages() -> None:
    with make_client() as client:
        employee = create_employee(client)
        set_annual_policy(client)
        sick = client.put(
            "/v1/leave/policies",
            json={
                "leave_type": "sick",
                "name": "Sakit",
                "accrual_method": "lump_sum_annual",
                "days_per_year": 6.0,
                "min_service_months": 0,
            },
        )
        assert sick.status_code == 200, sick.text

        whole = client.get(f"/v1/leave/balances/{employee['id']}")
        first = client.get(f"/v1/leave/balances/{employee['id']}", params={"limit": 1, "offset": 0})
        second = client.get(
            f"/v1/leave/balances/{employee['id']}", params={"limit": 1, "offset": 1}
        )

    assert whole.status_code == first.status_code == second.status_code == 200
    assert whole.json()["total"] == 2
    assert first.json()["total"] == second.json()["total"] == 2
    assert [item["leave_type"] for item in first.json()["items"]] == ["annual"]
    assert [item["leave_type"] for item in second.json()["items"]] == ["sick"]
    paged_types = [item["leave_type"] for item in first.json()["items"] + second.json()["items"]]
    assert paged_types == [item["leave_type"] for item in whole.json()["items"]]


def test_calendar_listing_pages() -> None:
    with make_client() as client:
        set_annual_policy(client)
        for name in ("Sari Dewi", "Budi Santoso"):
            employee = create_employee(client, full_name=name)
            created = client.post(
                "/v1/leave",
                json={
                    "employee_id": employee["id"],
                    "leave_type": "annual",
                    "start_date": WORK_START.isoformat(),
                    "end_date": (WORK_START + timedelta(days=1)).isoformat(),
                },
            ).json()
            client.post(f"/v1/approvals/{created['approval_id']}/decide", json={"approve": True})
            client.post(f"/v1/leave/approvals/{created['approval_id']}/sync", json={})

        params = {"on_date": WORK_START.isoformat()}
        whole = client.get("/v1/leave/calendar", params=params)
        page = client.get("/v1/leave/calendar", params={**params, "limit": 1, "offset": 1})

    assert whole.status_code == page.status_code == 200
    assert whole.json()["total"] == 2
    assert page.json()["total"] == 2
    assert len(page.json()["items"]) == 1
    assert page.json()["items"][0]["id"] == whole.json()["items"][1]["id"]


def test_policy_listing_pages() -> None:
    with make_client() as client:
        set_annual_policy(client)
        sick = client.put(
            "/v1/leave/policies",
            json={
                "leave_type": "sick",
                "name": "Sakit",
                "accrual_method": "lump_sum_annual",
                "days_per_year": 6.0,
                "min_service_months": 0,
            },
        )
        assert sick.status_code == 200, sick.text

        whole = client.get("/v1/leave/policies")
        first = client.get("/v1/leave/policies", params={"limit": 1, "offset": 0})
        second = client.get("/v1/leave/policies", params={"limit": 1, "offset": 1})

    assert whole.status_code == first.status_code == second.status_code == 200
    assert whole.json()["total"] == 2
    assert first.json()["total"] == second.json()["total"] == 2
    paged_types = [item["leave_type"] for item in first.json()["items"] + second.json()["items"]]
    assert paged_types == [item["leave_type"] for item in whole.json()["items"]]


def test_listing_paging_bounds_are_rejected() -> None:
    with make_client() as client:
        employee = create_employee(client)
        paths = (
            "/v1/leave",
            f"/v1/leave/balances/{employee['id']}",
            "/v1/leave/calendar",
            "/v1/leave/policies",
        )
        for path in paths:
            assert client.get(path, params={"limit": 0}).status_code == 422, path
            assert client.get(path, params={"limit": 201}).status_code == 422, path
            assert client.get(path, params={"offset": -1}).status_code == 422, path
