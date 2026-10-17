"""The compliance calendar: derived deadlines merged with operator entries.

The API answers one list from two sources -- dates the system can compute from
records it already keeps, and dates only an operator can enter (which must
name their source). These tests pin the merge order, the overdue rule, the
provenance requirement and the audit trail of a removal.
"""

from datetime import timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import business_today
from hr_agents.rbac import RoleId

TODAY = business_today()


def make_client() -> TestClient:
    return TestClient(create_app())


def create_employee(
    client: TestClient,
    *,
    full_name: str = "Sari Dewi",
    probation_end: object | None = None,
) -> dict:
    payload: dict = {
        "full_name": full_name,
        "hire_date": (TODAY - timedelta(days=330)).isoformat(),
    }
    if probation_end is not None:
        payload["probation_end_date"] = probation_end
    response = client.post("/v1/employees", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def add_expiring_document(client: TestClient, employee_id: str, *, expires_on: object) -> None:
    response = client.post(
        f"/v1/employees/{employee_id}/documents",
        json={
            "kind": "ktp",
            "storage_key": "vault/ktp.pdf",
            "sha256": "a" * 64,
            "expires_on": expires_on,
        },
    )
    assert response.status_code == 201, response.text


def add_entry(client: TestClient, **overrides: object) -> dict:
    payload: dict = {
        "title": "PPh 21 monthly filing",
        "due_on": (TODAY + timedelta(days=5)).isoformat(),
        "category": "tax",
        "source_note": "DJP announcement 2026-01",
    }
    payload.update(overrides)
    response = client.post("/v1/compliance/calendar/entries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def calendar(client: TestClient, *, back: int = 30, ahead: int = 30) -> dict:
    response = client.get(
        "/v1/compliance/calendar",
        params={
            "start": (TODAY - timedelta(days=back)).isoformat(),
            "end": (TODAY + timedelta(days=ahead)).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_window_merges_deadlines_and_entries_in_due_order() -> None:
    with make_client() as client:
        employee = create_employee(client, probation_end=(TODAY + timedelta(days=20)).isoformat())
        add_expiring_document(
            client, employee["id"], expires_on=(TODAY + timedelta(days=10)).isoformat()
        )
        add_entry(client, due_on=(TODAY + timedelta(days=15)).isoformat())

        body = calendar(client)

    assert body["total"] == 3
    kinds = [(item["due_on"], item["source"], item["kind"]) for item in body["items"]]
    assert kinds == [
        ((TODAY + timedelta(days=10)).isoformat(), "deadline", "document_expiry"),
        ((TODAY + timedelta(days=15)).isoformat(), "entry", "tax"),
        ((TODAY + timedelta(days=20)).isoformat(), "deadline", "probation_end"),
    ]
    entry = body["items"][1]
    assert entry["title"] == "PPh 21 monthly filing"
    assert entry["source_note"] == "DJP announcement 2026-01"
    assert entry["overdue"] is False


def test_overdue_is_computed_against_the_business_day() -> None:
    with make_client() as client:
        employee = create_employee(client)
        add_expiring_document(
            client, employee["id"], expires_on=(TODAY - timedelta(days=2)).isoformat()
        )
        add_entry(client, due_on=(TODAY - timedelta(days=1)).isoformat())

        body = calendar(client)

    by_kind = {item["kind"]: item for item in body["items"]}
    assert by_kind["document_expiry"]["overdue"] is True
    assert by_kind["tax"]["overdue"] is True


def test_items_outside_the_window_are_not_returned() -> None:
    with make_client() as client:
        employee = create_employee(client, probation_end=(TODAY + timedelta(days=200)).isoformat())
        add_expiring_document(
            client, employee["id"], expires_on=(TODAY + timedelta(days=2)).isoformat()
        )
        add_entry(client, due_on=(TODAY + timedelta(days=3)).isoformat())

        body = calendar(client)

    assert [item["kind"] for item in body["items"]] == ["document_expiry", "tax"]


def test_entries_require_a_source_note_and_a_known_category() -> None:
    with make_client() as client:
        no_note = client.post(
            "/v1/compliance/calendar/entries",
            json={
                "title": "THR payout window",
                "due_on": TODAY.isoformat(),
                "category": "thr",
                "source_note": "",
            },
        )
        unknown_category = client.post(
            "/v1/compliance/calendar/entries",
            json={
                "title": "Something",
                "due_on": TODAY.isoformat(),
                "category": "vibes",
                "source_note": "trust me",
            },
        )

    assert no_note.status_code == 422
    assert unknown_category.status_code == 422


def test_removing_an_entry_requires_a_reason_and_audits_it() -> None:
    with make_client() as client:
        entry = add_entry(client)

        no_reason = client.request(
            "DELETE",
            f"/v1/compliance/calendar/entries/{entry['entry_id']}",
            json={"reason": ""},
        )
        assert no_reason.status_code == 422

        removed = client.request(
            "DELETE",
            f"/v1/compliance/calendar/entries/{entry['entry_id']}",
            json={"reason": "date was wrong"},
        )
        assert removed.status_code == 204

        again = client.request(
            "DELETE",
            f"/v1/compliance/calendar/entries/{entry['entry_id']}",
            json={"reason": "ping"},
        )
        assert again.status_code == 404

        trail = client.get(
            "/v1/compliance/audit/entries",
            params={"action": "compliance.calendar_entry_removed"},
        )
        assert trail.status_code == 200
        entries = trail.json()["items"]
        assert len(entries) == 1
        assert entries[0]["payload"]["reason"] == "date was wrong"
        assert entries[0]["payload"]["due_on"] == entry["due_on"]


def test_inverted_window_is_refused() -> None:
    with make_client() as client:
        response = client.get(
            "/v1/compliance/calendar",
            params={
                "start": TODAY.isoformat(),
                "end": (TODAY - timedelta(days=1)).isoformat(),
            },
        )

    assert response.status_code == 422


def test_calendar_requires_compliance_read() -> None:
    settings = Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1")
        ],
    )

    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/v1/compliance/calendar",
            params={"start": TODAY.isoformat(), "end": TODAY.isoformat()},
            headers={"X-API-Key": "fin-key"},
        )

    assert response.status_code == 403
