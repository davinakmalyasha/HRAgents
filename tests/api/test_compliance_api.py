"""Integration tests for the compliance API surface."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from hr_agents.main import create_app

NOW = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)


def make_client() -> TestClient:
    return TestClient(create_app())


def set_policy(client: TestClient, *, action: str = "anonymize", entity: str = "candidate") -> None:
    response = client.put(
        "/v1/compliance/retention/policies",
        json={
            "entity": entity,
            "name": f"{entity.title()} records",
            "retention_months": 24,
            "updated_by": "hr-admin",
            "expiry_action": action,
        },
    )
    assert response.status_code == 200, response.text


def track_candidate(
    client: TestClient, *, subject_id: str = "cand-1", anchor_at: str | None = None
) -> dict:
    response = client.post(
        "/v1/compliance/retention/records",
        json={
            "entity": "candidate",
            "subject_kind": "candidate",
            "subject_id": subject_id,
            "created_by": "screening-pipeline",
            "label": "Budi Santoso",
            "anchor_at": anchor_at or (NOW - timedelta(days=800)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- consent ------------------------------------------------------------------


def test_consent_register_status_revoke() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/compliance/consents",
            json={
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "purpose": "recruitment_evaluation",
                "captured_by": "screening-agent",
                "capture_method": "web_form",
            },
        )
        assert created.status_code == 201, created.text
        consent_id = created.json()["id"]

        status = client.get(
            "/v1/compliance/consents/status",
            params={"subject_kind": "candidate", "subject_id": "cand-1"},
        )
        assert status.status_code == 200
        assert status.json()["active_purposes"] == ["recruitment_evaluation"]

        agent_revoke = client.post(
            f"/v1/compliance/consents/{consent_id}/revoke",
            json={"by": "agent:policy_assistant", "reason": "subject asked"},
        )
        assert agent_revoke.status_code == 409

        revoked = client.post(
            f"/v1/compliance/consents/{consent_id}/revoke",
            json={"by": "hr-admin", "reason": "subject asked"},
        )
        assert revoked.status_code == 200
        assert revoked.json()["active"] is False

        listed = client.get("/v1/compliance/consents", params={"subject_id": "cand-1"})
        assert len(listed.json()) == 1


# --- retention ----------------------------------------------------------------


def test_retention_scan_purge_and_hold_flow() -> None:
    with make_client() as client:
        set_policy(client, action="delete")
        first = track_candidate(client, subject_id="cand-1")
        second = track_candidate(client, subject_id="cand-2")

        held = client.post(
            f"/v1/compliance/retention/records/{second['id']}/hold",
            json={"held": True, "by": "hr-admin", "reason": "litigation hold"},
        )
        assert held.status_code == 200
        assert held.json()["legal_hold"] is True

        scan = client.get("/v1/compliance/retention/scan")
        assert scan.status_code == 200
        body = scan.json()
        assert len(body["due"]) == 1
        assert len(body["held"]) == 1

        dry_run = client.post(
            "/v1/compliance/retention/purge", json={"by": "system", "dry_run": True}
        )
        assert dry_run.status_code == 200
        assert dry_run.json()["dry_run"] is True
        assert len(dry_run.json()["purged"]) == 1

        executed = client.post("/v1/compliance/retention/purge", json={"by": "system"})
        assert executed.status_code == 200
        # The candidate entity has no store handler, so the purge is skipped
        # rather than falsely reported. See the dedicated test below.
        assert executed.json()["purged"] == []
        assert executed.json()["skipped"][0]["action"] == "delete"

        records = client.get(
            "/v1/compliance/retention/records",
            params={"subject_id": "cand-1", "include_purged": True},
        )
        assert records.json()[0]["purged_at"] is None

        held_still = client.get("/v1/compliance/retention/records", params={"subject_id": "cand-2"})
        assert held_still.json()[0]["purged_at"] is None
        assert first["id"] != second["id"]


def test_purge_reports_skip_when_the_entity_has_no_store_handler() -> None:
    """A purge must never claim to have removed data it did not remove.

    Only ``consent`` has a registered store handler in the shipped composition
    root. A candidate record is therefore *skipped*: reported, audited, and
    explicitly not marked purged, so the ledger and the API agree that the data
    is still present.
    """
    with make_client() as client:
        set_policy(client, action="delete")
        track_candidate(client, subject_id="cand-1")

        response = client.post("/v1/compliance/retention/purge", json={"by": "system"})
        assert response.status_code == 200
        body = response.json()

        assert body["purged"] == []
        assert len(body["skipped"]) == 1
        skipped = body["skipped"][0]
        assert skipped["entity"] == "candidate"
        assert skipped["status"] == "skipped"
        assert skipped["purged"] is False

        records = client.get("/v1/compliance/retention/records", params={"include_purged": True})
        assert records.json()[0]["purged_at"] is None


def test_consent_purge_actually_removes_the_grant() -> None:
    """The one entity with a real handler must really remove its data."""
    with make_client() as client:
        set_policy(client, action="delete", entity="consent")
        client.post(
            "/v1/compliance/consents",
            json={
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "purpose": "recruitment_evaluation",
                "captured_by": "hr-admin",
            },
        )
        client.post(
            "/v1/compliance/retention/records",
            json={
                "entity": "consent",
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "created_by": "compliance",
                "anchor_at": (NOW - timedelta(days=900)).isoformat(),
            },
        )
        before = client.get("/v1/compliance/consents", params={"subject_id": "cand-1"})
        assert len(before.json()) == 1

        response = client.post("/v1/compliance/retention/purge", json={"by": "system"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["purged"]) == 1
        assert body["purged"][0]["entity"] == "consent"
        assert body["purged"][0]["purged"] is True

        after = client.get("/v1/compliance/consents", params={"subject_id": "cand-1"})
        assert after.json() == []


def test_retention_uncovered_entity_reported() -> None:
    with make_client() as client:
        response = client.post(
            "/v1/compliance/retention/records",
            json={
                "entity": "document",
                "subject_kind": "employee",
                "subject_id": "emp-1",
                "created_by": "records",
                "anchor_at": (NOW - timedelta(days=900)).isoformat(),
            },
        )
        assert response.status_code == 201

        scan = client.get("/v1/compliance/retention/scan")

    assert len(scan.json()["uncovered"]) == 1
    assert scan.json()["due"] == []


def test_agent_purge_rejected() -> None:
    with make_client() as client:
        response = client.post("/v1/compliance/retention/purge", json={"by": "agent:records"})

    assert response.status_code == 409


# --- erasure ------------------------------------------------------------------


def test_erasure_end_to_end_requires_human_approval() -> None:
    with make_client() as client:
        set_policy(client, action="anonymize")
        record = track_candidate(client, subject_id="cand-1")
        client.post(
            f"/v1/compliance/retention/records/{record['id']}/hold",
            json={"held": True, "by": "hr-admin", "reason": "litigation"},
        )
        other = track_candidate(client, subject_id="cand-1")
        client.post(
            "/v1/compliance/consents",
            json={
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "purpose": "recruitment_evaluation",
                "captured_by": "hr-admin",
            },
        )

        created = client.post(
            "/v1/compliance/erasures",
            json={
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "reason": "UU PDP erasure request",
                "requested_by": "hr-admin",
            },
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]

        premature = client.post(
            f"/v1/compliance/erasures/{request_id}/submit", json={"by": "hr-admin"}
        )
        assert premature.status_code == 409

        verified = client.post(
            f"/v1/compliance/erasures/{request_id}/verify",
            json={"by": "hr-admin", "method": "email reply"},
        )
        assert verified.status_code == 200

        submitted = client.post(
            f"/v1/compliance/erasures/{request_id}/submit", json={"by": "hr-admin"}
        )
        assert submitted.status_code == 200
        approval_id = submitted.json()["approval_id"]

        decision = client.post(
            f"/v1/approvals/{approval_id}/decide",
            json={"decided_by": "dpo-nadia", "approve": True, "reason": "verified request"},
        )
        assert decision.status_code == 200, decision.text

        synced = client.post(f"/v1/compliance/erasures/approvals/{approval_id}/sync")
        assert synced.status_code == 200
        assert synced.json()["status"] == "approved"

        executed = client.post(
            f"/v1/compliance/erasures/{request_id}/execute", json={"by": "hr-admin"}
        )
        assert executed.status_code == 200, executed.text
        body = executed.json()
        assert body["status"] == "executed"
        assert body["consents_revoked"] == 1
        actions = {item["action"] for item in body["dispositions"]}
        # A candidate record has no registered store purge handler, so its
        # disposition is not_executed — not "anonymized". The held record is
        # still retained. Neither claim may be false.
        assert actions == {"not_executed", "retained_legal_hold"}
        assert body["dispositions"][1]["record_id"] == str(other["id"])


def test_erasure_unknown_returns_404() -> None:
    with make_client() as client:
        response = client.get("/v1/compliance/erasures/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


# --- breach -------------------------------------------------------------------


def test_breach_checklist_flow() -> None:
    with make_client() as client:
        template = client.get("/v1/compliance/breaches/template")
        assert template.status_code == 200
        assert len(template.json()["steps"]) >= 4

        created = client.post(
            "/v1/compliance/breaches",
            json={
                "title": "Laptop with HR export lost",
                "description": "Device encryption status unknown",
                "impact": "high",
                "discovered_by": "it-ops",
                "created_by": "hr-admin",
                "discovered_at": NOW.isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        incident_id = created.json()["id"]

        agent_step = client.post(
            f"/v1/compliance/breaches/{incident_id}/steps/contain/complete",
            json={"by": "agent:compliance"},
        )
        assert agent_step.status_code == 409

        completed = client.post(
            f"/v1/compliance/breaches/{incident_id}/steps/contain/complete",
            json={"by": "it-ops", "note": "device remote-wiped"},
        )
        assert completed.status_code == 200
        assert completed.json()["steps"][0]["completed"] is True

        notified_without_record = client.post(
            f"/v1/compliance/breaches/{incident_id}/status",
            json={"status": "notified", "by": "hr-admin"},
        )
        assert notified_without_record.status_code == 409

        client.post(
            f"/v1/compliance/breaches/{incident_id}/notifications",
            json={
                "recipient_kind": "regulator",
                "recipient": "authority portal",
                "sent_by": "hr-admin",
                "reference": "ticket-42",
            },
        )
        notified = client.post(
            f"/v1/compliance/breaches/{incident_id}/status",
            json={"status": "notified", "by": "hr-admin", "note": "notice sent"},
        )
        assert notified.status_code == 200
        assert notified.json()["status"] == "notified"

        for step in notified.json()["steps"]:
            if step["required"] and not step["completed"]:
                client.post(
                    f"/v1/compliance/breaches/{incident_id}/steps/{step['key']}/complete",
                    json={"by": "hr-admin"},
                )

        closed = client.post(
            f"/v1/compliance/breaches/{incident_id}/status",
            json={"status": "closed", "by": "hr-admin", "note": "post-mortem done"},
        )
        assert closed.status_code == 200, closed.text
        assert closed.json()["status"] == "closed"

        overdue = client.get("/v1/compliance/breaches/overdue", params={"as_of": NOW.isoformat()})
        assert overdue.status_code == 200
        assert overdue.json() == []


def test_breach_close_requires_note() -> None:
    with make_client() as client:
        created = client.post(
            "/v1/compliance/breaches",
            json={
                "title": "Misdirected email",
                "description": "",
                "impact": "medium",
                "discovered_by": "hr-admin",
                "created_by": "hr-admin",
                "discovered_at": NOW.isoformat(),
            },
        )
        incident_id = created.json()["id"]

        response = client.post(
            f"/v1/compliance/breaches/{incident_id}/status",
            json={"status": "closed", "by": "hr-admin"},
        )

    assert response.status_code == 409


# --- audit --------------------------------------------------------------------


def test_audit_verify_reports_intact_chain() -> None:
    with make_client() as client:
        client.post(
            "/v1/compliance/consents",
            json={
                "subject_kind": "candidate",
                "subject_id": "cand-1",
                "purpose": "recruitment_evaluation",
                "captured_by": "hr-admin",
            },
        )
        report = client.get("/v1/compliance/audit/verify", params={"checked_by": "auditor"})

    assert report.status_code == 200
    body = report.json()
    assert body["intact"] is True
    assert body["entry_count"] >= 1
    assert body["first_invalid_seq"] is None
