"""Integration tests for the payroll API surface."""

from datetime import timedelta
from uuid import UUID

from fastapi.testclient import TestClient

from hr_agents.identity import ActorRef
from hr_agents.main import create_app
from hr_agents.models import business_today
from hr_agents.models.money import money as m

TODAY = business_today()
YEAR = TODAY.year


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(client: TestClient) -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": "Sari Dewi",
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
            "job_title": "Finance Staff",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def seed_tables(client: TestClient) -> None:
    """Create + verify the rate tables payroll requires (illustrative values)."""
    specs = [
        ("bpjs_kesehatan", 4.0, 1.0, 12_000_000.0),
        ("bpjs_ketenagakerjaan_jht", 3.7, 2.0, None),
        ("bpjs_ketenagakerjaan_jp", 2.0, 1.0, 10_000_000.0),
        ("bpjs_jkk", 0.24, None, None),
        ("bpjs_jkm", 0.3, None, None),
    ]
    for kind, employer, employee, cap in specs:
        created = client.post(
            "/v1/rate-tables",
            json={"kind": kind, "name": kind},
        )
        assert created.status_code == 201, created.text
        table_id = UUID(created.json()["id"])
        # Note: entries/verify endpoints are service-level; use the app state directly.
        app_state = client.app.state.people.rate_tables  # type: ignore[attr-defined]
        from hr_agents.models import RateEntry

        app_state.set_entries(
            table_id,
            entries=[
                RateEntry(
                    label="standard",
                    employer_share_percent=employer,
                    employee_share_percent=employee,
                    wage_cap=m(cap) if cap is not None else None,
                )
            ],
            actor=ActorRef.legacy("hr-admin"),
        )
        app_state.verify(
            table_id,
            actor=ActorRef.legacy("hr-admin"),
            source_note="test fixture",
        )

    overtime = client.post(
        "/v1/rate-tables",
        json={"kind": "overtime_premium", "name": "OT"},
    ).json()["id"]
    app_state = client.app.state.people.rate_tables  # type: ignore[attr-defined]
    from hr_agents.models import RateEntry

    app_state.set_entries(
        UUID(overtime),
        entries=[
            RateEntry(key="monthly_hours", label="Monthly hours", hours_per_month=173.0),
            RateEntry(key="first_hour", label="First hour each day", multiplier=1.5),
            RateEntry(key="subsequent_hour", label="Subsequent hours", multiplier=2.0),
        ],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(overtime), actor=ActorRef.legacy("hr"), source_note="fixture")

    pph = client.post(
        "/v1/rate-tables",
        json={"kind": "pph21_ter", "name": "TER"},
    ).json()["id"]
    app_state.set_entries(
        UUID(pph),
        entries=[
            RateEntry(
                label="low", lower_bound=m(0), upper_bound=m(15_000_000), employee_share_percent=2.0
            )
        ],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(pph), actor=ActorRef.legacy("hr"), source_note="fixture")

    ptkp = client.post(
        "/v1/rate-tables",
        json={"kind": "pph21_ptkp", "name": "PTKP"},
    ).json()["id"]
    app_state.set_entries(
        UUID(ptkp),
        entries=[
            RateEntry(key="personal", label="Self", flat_amount=m(54_000_000)),
            RateEntry(key="dependent", label="Per dependent", flat_amount=m(6_750_000)),
        ],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(ptkp), actor=ActorRef.legacy("hr"), source_note="fixture")

    minimum = client.post(
        "/v1/rate-tables",
        json={"kind": "minimum_wage", "name": "Minimum wage"},
    ).json()["id"]
    app_state.set_entries(
        UUID(minimum),
        entries=[RateEntry(label="Regional minimum", flat_amount=m(2_500_000))],
        actor=ActorRef.legacy("hr"),
    )
    app_state.verify(UUID(minimum), actor=ActorRef.legacy("hr"), source_note="fixture")


def test_payroll_full_flow_without_tables_blocks() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        inputs = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        assert inputs.status_code == 200
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})

    assert computed.status_code == 200
    body = computed.json()
    assert body["blocking_count"] > 0
    assert any(a["severity"] == "error" for a in body["anomalies"])


def test_signoff_blocked_when_anomalies_present() -> None:
    with make_client() as client:
        employee = create_employee(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 5_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={})

    assert submitted.status_code == 409
    assert "blocking anomalies" in submitted.json()["title"]


def test_payroll_full_flow_with_tables() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)

        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [
                    {
                        "employee_id": employee["id"],
                        "base_salary": 9_000_000,
                        "fixed_allowances": 1_000_000,
                        "overtime_hours": 2,
                    }
                ],
            },
        )
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={}).json()

        assert computed["blocking_count"] == 0
        line = computed["lines"][0]
        assert line["employee_name"] == "Sari Dewi"
        assert line["net"] < line["gross"]

        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={}).json()
        approval_id = submitted["approval_id"]
        assert approval_id

        decided = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"approve": True},
        )
        assert decided.status_code == 200

        synced = client.post(f"/v1/payroll/approvals/{approval_id}/sync", json={})
        assert synced.status_code == 200
        assert synced.json()["status"] == "approved"
        assert synced.json()["signed_off_by"] == "local-dev"

        packet = client.get(f"/v1/payroll/runs/{run['id']}/packet.xlsx")
        assert packet.status_code == 200
        assert packet.headers["content-type"].startswith("application/vnd.openxmlformats")
        assert "no payments executed" in packet.headers["x-hragents-notice"]

        exported = client.post(f"/v1/payroll/runs/{run['id']}/export", json={})
        assert exported.json()["status"] == "exported"


def test_supersede_freezes_the_reviewed_run_and_links_a_successor() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={"inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}]},
        )
        computed = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={}).json()
        assert computed["blocking_count"] == 0

        missing_reason = client.post(f"/v1/payroll/runs/{run['id']}/supersede", json={})
        assert missing_reason.status_code == 422

        superseded = client.post(
            f"/v1/payroll/runs/{run['id']}/supersede",
            json={"reason": "rate table corrected"},
        )
        assert superseded.status_code == 201, superseded.text
        successor = superseded.json()
        assert successor["supersedes_id"] == run["id"]
        assert successor["status"] == "assembling"
        assert successor["lines"] == []

        reviewed = client.get(f"/v1/payroll/runs/{run['id']}").json()
        assert reviewed["status"] == "superseded"
        assert reviewed["lines"] == computed["lines"]

        recompute = client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        assert recompute.status_code == 409
        assert "supersede" in recompute.json()["title"]

        updated = client.put(
            f"/v1/payroll/runs/{successor['id']}/inputs",
            json={"inputs": [{"employee_id": employee["id"], "base_salary": 9_500_000}]},
        )
        assert updated.status_code == 200
        recomputed = client.post(f"/v1/payroll/runs/{successor['id']}/compute", json={})
        assert recomputed.status_code == 200
        assert recomputed.json()["status"] == "ready_for_review"


def test_approval_decision_refuses_a_caller_supplied_actor() -> None:
    """A decision cannot be attributed by naming someone in the body.

    The old assertion was a 409 with "named human" in it, which is what the
    service returned when a body said ``decided_by="agent:payroll_bot"``. No
    request can name an actor now, so the attempt is refused at the boundary --
    the stronger property. The gate itself lives in ``ApprovalEngine.decide`` and
    is covered in ``tests/test_named_human_gates.py``, where an agent actor can
    actually be constructed.
    """
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        submitted = client.post(f"/v1/payroll/runs/{run['id']}/submit", json={}).json()

        refused = client.post(
            f"/v1/approvals/{submitted['approval_id']}/decide",
            json={"approve": True, "decided_by": "agent:payroll_bot"},
        )
        approved = client.post(
            f"/v1/approvals/{submitted['approval_id']}/decide",
            json={"approve": True},
        )
        synced = client.post(f"/v1/payroll/approvals/{submitted['approval_id']}/sync", json={})

    assert refused.status_code == 422
    assert any(error["loc"][-1] == "decided_by" for error in refused.json()["detail"])
    assert approved.status_code == 200
    assert approved.json()["action"] == "approved"
    # and the run names the key's holder as the approver, not a typed-in name
    assert synced.json()["signed_off_by"] == "local-dev"


def test_edit_after_submission_rejected() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}],
            },
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        client.post(f"/v1/payroll/runs/{run['id']}/submit", json={})

        response = client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={
                "inputs": [{"employee_id": employee["id"], "base_salary": 1_000_000}],
            },
        )

    assert response.status_code == 409
    assert "no longer be edited" in response.json()["title"]


def test_cancelling_a_run_reports_why_through_the_view() -> None:
    """The reason has to reach the run view, not just the audit chain.

    The queue and the packet are where a person meets a cancelled run; a status
    with no why in either is what this closes.
    """
    app = create_app()
    with TestClient(app) as client:
        employee = create_employee(client)
        seed_tables(client)
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={"inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}]},
        )
        client.post(f"/v1/payroll/runs/{run['id']}/compute", json={})
        refused = client.post(f"/v1/payroll/runs/{run['id']}/cancel", json={"reason": "   "})
        cancelled = client.post(
            f"/v1/payroll/runs/{run['id']}/cancel", json={"reason": " duplicate period "}
        )
        listed = client.get("/v1/payroll/runs").json()

    # The router refuses a blank reason before the service does; either way it is a refusal.
    assert refused.status_code == 422
    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "duplicate period"
    assert body["cancelled_at"]

    same_run = next(item for item in listed["items"] if item["id"] == run["id"])
    assert same_run["cancel_reason"] == "duplicate period"


def test_list_runs_pages_the_unpaged_read() -> None:
    with make_client() as client:
        for month in (1, 2, 3):
            created = client.post(
                "/v1/payroll/runs",
                json={"period_year": YEAR, "period_month": month},
            )
            assert created.status_code == 201, created.text

        full = client.get("/v1/payroll/runs").json()
        page = client.get("/v1/payroll/runs", params={"limit": 2, "offset": 1}).json()
        beyond = client.get("/v1/payroll/runs", params={"limit": 2, "offset": 9}).json()

    all_ids = [item["id"] for item in full["items"]]
    assert full["total"] == 3
    assert len(full["items"]) == 3
    assert page["total"] == 3
    assert page["limit"] == 2
    assert page["offset"] == 1
    assert [item["id"] for item in page["items"]] == all_ids[1:3]
    assert beyond["items"] == []
    assert beyond["total"] == 3


def test_list_runs_rejects_invalid_pagination() -> None:
    with make_client() as client:
        too_small = client.get("/v1/payroll/runs", params={"limit": 0})
        too_big = client.get("/v1/payroll/runs", params={"limit": 201})
        negative = client.get("/v1/payroll/runs", params={"offset": -1})

    assert too_small.status_code == 422
    assert too_big.status_code == 422
    assert negative.status_code == 422


def _june_workdays(count: int) -> list[str]:
    from datetime import date as va_date

    days: list[str] = []
    day = 1
    while len(days) < count:
        candidate = va_date(YEAR, 6, day)
        if candidate.weekday() < 5:
            days.append(candidate.isoformat())
        day += 1
    return days


def _create_numbered_employee(client: TestClient, number: str) -> dict:
    response = client.post(
        "/v1/employees",
        json={
            "full_name": f"Sari {number}",
            "hire_date": (TODAY - timedelta(days=400)).isoformat(),
            "job_title": "Staff",
            "employee_number": number,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_attendance_preview_and_commit_fill_worked_time() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = _create_numbered_employee(client, "EMP-101")
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={"inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}]},
        )
        first, second = _june_workdays(2)
        csv_text = (
            "employee_number,date,clock_in,clock_out\n"
            f"EMP-101,{first},08:00,18:00\n"
            f"EMP-101,{second},08:00,17:00\n"
        )
        preview = client.post(
            f"/v1/payroll/runs/{run['id']}/attendance:preview",
            json={"csv_text": csv_text},
        )
        assert preview.status_code == 200, preview.text
        body = preview.json()
        assert body["errors"] == []
        assert body["rows"][0]["days_present"] == 2
        assert body["rows"][0]["overtime_hours"] == 3.0

        committed = client.post(
            f"/v1/payroll/runs/{run['id']}/attendance:commit",
            json={"csv_text": csv_text},
        )
        assert committed.status_code == 200, committed.text

        fetched = client.get(f"/v1/payroll/runs/{run['id']}").json()
        assert fetched["lines"] == []


def test_attendance_commit_refuses_bad_rows_without_mutating() -> None:
    app = create_app()
    with TestClient(app) as client:
        employee = _create_numbered_employee(client, "EMP-102")
        run = client.post(
            "/v1/payroll/runs",
            json={"period_year": YEAR, "period_month": 6},
        ).json()
        client.put(
            f"/v1/payroll/runs/{run['id']}/inputs",
            json={"inputs": [{"employee_id": employee["id"], "base_salary": 9_000_000}]},
        )
        first = _june_workdays(1)[0]
        refused = client.post(
            f"/v1/payroll/runs/{run['id']}/attendance:commit",
            json={
                "csv_text": (
                    f"employee_number,date,clock_in,clock_out\nGHOST-1,{first},08:00,17:00\n"
                )
            },
        )
        assert refused.status_code == 409

        preview = client.post(
            f"/v1/payroll/runs/{run['id']}/attendance:preview",
            json={
                "csv_text": (
                    f"employee_number,date,clock_in,clock_out\nGHOST-1,{first},08:00,17:00\n"
                )
            },
        )
        assert preview.status_code == 200
        assert preview.json()["errors"] != []


def test_attendance_preview_unknown_run_is_404() -> None:
    from uuid import uuid4

    with make_client() as client:
        response = client.post(
            f"/v1/payroll/runs/{uuid4()}/attendance:preview",
            json={"csv_text": "employee_number,date,clock_in,clock_out\n"},
        )
    assert response.status_code == 404
