"""API-level RBAC: role-bound keys gate router access."""

from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId


def _settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1"),
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1"),
            ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="emp-1"),
        ],
    )


def _payroll_payload() -> dict:
    return {
        "period_year": date.today().year,
        "period_month": 6,
    }


def test_recruiter_can_read_recruiting_but_not_payroll() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        queue = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "rec-key"},
        )
        assert queue.status_code == 200

        payroll = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "rec-key"},
        )
        assert payroll.status_code == 403


def test_finance_can_create_payroll_but_not_read_recruiting() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        run = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "fin-key"},
        )
        assert run.status_code == 201

        queue = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "fin-key"},
        )
        assert queue.status_code == 403


def test_manager_can_decide_approvals_but_not_payroll() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        payroll = client.post(
            "/v1/payroll/runs",
            json=_payroll_payload(),
            headers={"X-API-Key": "emp-key"},
        )
        assert payroll.status_code == 403

        approvals = client.get("/v1/approvals", headers={"X-API-Key": "emp-key"})
        assert approvals.status_code == 403


def test_missing_or_wrong_key_is_401() -> None:
    app = create_app(_settings())
    with TestClient(app) as client:
        missing = client.get("/v1/queue", params={"job_id": str(uuid4())})
        assert missing.status_code == 401

        wrong = client.get(
            "/v1/queue",
            params={"job_id": str(uuid4())},
            headers={"X-API-Key": "nope"},
        )
        assert wrong.status_code == 401


def test_unconfigured_auth_allows_local_admin() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.get("/v1/queue", params={"job_id": str(uuid4())})
        assert response.status_code == 200


def _agent_settings() -> Settings:
    """A principal whose actor id claims to be an agent tool.

    The request body can no longer name an actor, so the only remaining way to
    reach a named-human gate with a non-human identity is to configure one. That
    makes this a real hole, not a hypothetical, and the gates still have to
    refuse it.
    """
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(
                key=SecretStr("bot-key"), role=RoleId.HR_ADMIN, actor_id="agent:hr_bot"
            ),
        ],
    )


def test_a_configured_agent_actor_still_cannot_decide() -> None:
    """Authentication establishes who; it does not make an agent a person.

    The 403 branches in the routers are only reachable through a principal like
    this one now that request bodies cannot supply an actor, so this test is what
    keeps those branches honest instead of letting them rot into dead code.
    """
    app = create_app(_agent_settings())
    with TestClient(app) as client:
        headers = {"X-API-Key": "bot-key"}
        offer_refused = client.put(
            "/v1/leave/policies",
            json={"leave_type": "annual", "name": "Annual leave"},
            headers=headers,
        )
        approvals = client.get("/v1/approvals", headers=headers)
        opened = client.post(
            "/v1/approvals",
            json={
                "subject": "candidate_rejection",
                "subject_id": "cand-1",
                "title": "Rejection sign-off",
                "assignee_role": "engineering_lead",
            },
            headers=headers,
        )
        decided = client.post(
            f"/v1/approvals/{opened.json()['id']}/decide",
            json={"approve": True},
            headers=headers,
        )

    # The policy write is refused by the named-human gate, not by RBAC: the role
    # is hr_admin, which holds the permission.
    assert offer_refused.status_code == 409
    assert "named human" in offer_refused.json()["title"]
    # reading the approval queue is fine, and so is raising an approval
    assert approvals.status_code == 200
    assert opened.status_code == 201
    # deciding is not: an authenticated agent is still an agent
    assert decided.status_code == 409
    assert "named human" in decided.json()["title"]
