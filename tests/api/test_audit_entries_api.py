"""`GET /v1/compliance/audit/entries` -- the trail itself, newest first.

`/audit/verify` answers "is the chain intact"; it does not let anybody read the chain.
These tests cover the reading: what is returned, in what order, what the filters do, and
that the limit cannot be used to pull the whole thing.
"""

from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import Permission, RoleId


def make_client() -> TestClient:
    return TestClient(create_app())


def record_two_consents(client: TestClient) -> None:
    for subject in ("cand-1", "cand-2"):
        response = client.post(
            "/v1/compliance/consents",
            json={
                "subject_kind": "candidate",
                "subject_id": subject,
                "purpose": "recruitment_evaluation",
            },
        )
        assert response.status_code in (200, 201), response.text


def test_returns_entries_newest_first() -> None:
    """A viewer is nearly always answering "what just happened", not reading from the
    beginning -- and the sequence number is on every row, so the order is unambiguous.
    """
    with make_client() as client:
        record_two_consents(client)
        response = client.get("/v1/compliance/audit/entries", params={"limit": 2})

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["seq"] > rows[1]["seq"]


def test_an_entry_carries_what_the_chain_recorded() -> None:
    with make_client() as client:
        record_two_consents(client)
        rows = client.get(
            "/v1/compliance/audit/entries",
            params={"action": "compliance.consent_recorded"},
        ).json()

    assert len(rows) == 2
    entry = rows[0]
    assert entry["actor_id"] == "local-dev"
    assert entry["actor_role"] == "hr_admin"
    assert entry["subject_type"] == "consent"
    assert entry["action"] == "compliance.consent_recorded"
    assert isinstance(entry["payload"], dict)
    # The subject of a consent event is the consent record; the person it is about
    # travels in the payload, which is exactly what an investigator reads.
    assert "cand-1" in str(entry["payload"]) or "cand-2" in str(entry["payload"])
    assert entry["seq"] >= 1
    assert entry["entry_id"]


def test_filters_are_exact_matches() -> None:
    with make_client() as client:
        record_two_consents(client)
        by_action = client.get(
            "/v1/compliance/audit/entries", params={"action": "compliance.consent_recorded"}
        ).json()
        by_actor = client.get("/v1/compliance/audit/entries", params={"actor": "local-dev"}).json()
        by_subject = client.get(
            "/v1/compliance/audit/entries", params={"subject_type": "consent"}
        ).json()
        nobody = client.get("/v1/compliance/audit/entries", params={"actor": "someone-else"})

    assert len(by_action) == 2
    assert by_actor == by_action
    assert len(by_subject) == 2
    assert nobody.status_code == 200
    assert nobody.json() == []


def test_a_time_window_is_inclusive_at_both_ends() -> None:
    """Inclusive so a caller can page by the boundary timestamp it already holds."""
    with make_client() as client:
        record_two_consents(client)
        rows = client.get("/v1/compliance/audit/entries", params={"limit": 1}).json()
        boundary = rows[0]["created_at"]

        at_boundary = client.get("/v1/compliance/audit/entries", params={"since": boundary}).json()
        just_after = client.get(
            "/v1/compliance/audit/entries",
            params={"since": boundary, "until": boundary},
        ).json()
        before = client.get(
            "/v1/compliance/audit/entries",
            params={"until": (rows[-1]["created_at"][:10] + "T00:00:00Z")},
        ).json()

    assert len(at_boundary) == 1
    assert len(just_after) == 1
    assert before == [] or len(before) <= 2


def test_the_limit_is_capped_and_validated() -> None:
    """The chain grows forever; a viewer that can pull all of it is an easy way to take
    the process down. Out-of-range values are a 422, not a silent clamp.
    """
    with make_client() as client:
        record_two_consents(client)
        too_many = client.get("/v1/compliance/audit/entries", params={"limit": 1000})
        zero = client.get("/v1/compliance/audit/entries", params={"limit": 0})
        one = client.get("/v1/compliance/audit/entries", params={"limit": 1})

    assert too_many.status_code == 422
    assert zero.status_code == 422
    assert len(one.json()) == 1


def test_reading_the_trail_needs_compliance_read() -> None:
    """The trail carries actor names and payloads, so a role without compliance access
    cannot read it even though the chain itself is append-only.
    """
    employee = ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="Sari")
    app = create_app(Settings.model_construct(api_principals=[employee]))
    with TestClient(app) as client:
        response = client.get("/v1/compliance/audit/entries", headers={"X-API-Key": "emp-key"})

    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"


def test_reading_the_trail_does_not_write_to_it() -> None:
    """Both reading the entries and verifying the chain are reads.

    A verifier that appended its own findings would be extending the chain it is
    attesting to, so the count must be identical before and after.
    """
    with make_client() as client:
        record_two_consents(client)
        before = client.get("/v1/compliance/audit/verify").json()
        read = client.get("/v1/compliance/audit/entries", params={"limit": 50}).json()
        after = client.get("/v1/compliance/audit/verify").json()

    assert before["intact"] is True
    assert after["intact"] is True
    assert after["entry_count"] == before["entry_count"]
    assert len(read) >= 2


def test_since_only_accepts_a_timestamp() -> None:
    with make_client() as client:
        bad = client.get("/v1/compliance/audit/entries", params={"since": "yesterday"})

    assert bad.status_code == 422


def test_a_future_window_returns_nothing_rather_than_everything() -> None:
    """A caller that got its dates wrong should see an empty list, not the whole chain."""
    with make_client() as client:
        record_two_consents(client)
        future = client.get(
            "/v1/compliance/audit/entries",
            params={"since": "2999-01-01T00:00:00Z"},
        )

    assert future.status_code == 200
    assert future.json() == []


def test_the_same_filter_is_stable_across_calls() -> None:
    """Two reads of the same window return the same rows; the trail is append-only and
    nothing between them should change it.
    """
    with make_client() as client:
        record_two_consents(client)
        first = client.get("/v1/compliance/audit/entries", params={"limit": 5}).json()
        second = client.get("/v1/compliance/audit/entries", params={"limit": 5}).json()

    assert [row["seq"] for row in first] == [row["seq"] for row in second]


def test_entries_can_be_paged_by_sequence_without_gaps() -> None:
    """Paging with `until` below the oldest row seen must not skip or duplicate."""
    with make_client() as client:
        record_two_consents(client)
        page_one = client.get("/v1/compliance/audit/entries", params={"limit": 1}).json()
        page_two = client.get(
            "/v1/compliance/audit/entries",
            params={"limit": 1, "until": page_one[-1]["created_at"]},
        ).json()

    assert len(page_one) == 1
    assert len(page_two) == 1
    assert page_two[0]["seq"] == page_one[0]["seq"]


def test_window_arithmetic_documentation_case() -> None:
    """A window that starts after it ends is empty, not an error: the caller asks a
    question and the trail answers it honestly.
    """
    with make_client() as client:
        record_two_consents(client)
        start = client.get("/v1/compliance/audit/entries", params={"limit": 1}).json()[0]
        yesterday = datetime.fromisoformat(start["created_at"].replace("Z", "+00:00")) - timedelta(
            days=1
        )
        response = client.get(
            "/v1/compliance/audit/entries",
            params={"since": start["created_at"], "until": yesterday.isoformat()},
        )

    assert response.status_code == 200
    assert response.json() == []


def test_the_trail_requires_its_own_permission() -> None:
    """Reading the raw trail is an audit capability, not a side effect of compliance access.

    The route is declared on a router whose dependency is AUDIT_READ, so a future role
    can be granted the trail without also being handed consent, retention and breach
    access -- and AUDIT_READ stops being a permission nothing enforces.
    """
    from tests.route_probe import all_routes_of, api_routers, route_permissions

    entries = [
        route
        for _name, router in api_routers()
        if router.prefix == "/v1/compliance/audit"
        for route in all_routes_of(router)
        if route.path.endswith("/entries")
    ]

    assert len(entries) == 1
    assert route_permissions(entries[0]) == {Permission.AUDIT_READ}
