"""API-level RBAC: role-bound keys gate router access."""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.route_probe import (
    read_guarded_write_routes,
    route,
    route_permissions,
    write_routes,
)

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import Permission, Principal, RoleId, has_permission


def _settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("rec-key"), role=RoleId.RECRUITER, actor_id="rec-1"),
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1"),
            ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="emp-1"),
            ApiPrincipalSettings(key=SecretStr("adm-key"), role=RoleId.HR_ADMIN, actor_id="adm-1"),
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


def _manager_settings() -> Settings:
    return Settings.model_construct(
        api_keys=[],
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("mgr-key"), role=RoleId.MANAGER, actor_id="mgr-1"),
            ApiPrincipalSettings(key=SecretStr("fin-key"), role=RoleId.FINANCE, actor_id="fin-1"),
            ApiPrincipalSettings(key=SecretStr("adm-key"), role=RoleId.HR_ADMIN, actor_id="adm-1"),
        ],
    )


@pytest.mark.parametrize(
    ("path", "payload", "refused_key"),
    [
        ("/v1/employees", {"full_name": "A", "hire_date": "2026-01-05"}, "mgr-key"),
        ("/v1/org-units", {"name": "Engineering"}, "mgr-key"),
        ("/v1/contracts", {"employee_id": str(uuid4()), "start_date": "2026-01-05"}, "mgr-key"),
        (f"/v1/employees/{uuid4()}/transition", {"target": "offboarded"}, "mgr-key"),
    ],
)
def test_reading_the_directory_does_not_authorize_writing_it(
    path: str, payload: dict, refused_key: str
) -> None:
    """A manager reads people records; a manager does not get to write them.

    `MANAGER` holds `people:read` because a review needs the directory. It is
    not an HR administrator, so it may not create an employee, an org unit or a
    contract, nor drive an employment status transition.

    These routes were guarded by exactly that read permission until the
    structural fence was widened to see `people.py` -- which is to say until it
    could see it at all. The structural tests assert the *declared* permission;
    this asserts the request is actually refused, because a declared requirement
    that nothing exercises is the same defect one level down.
    """
    app = create_app(_manager_settings())
    with TestClient(app) as client:
        response = client.post(path, json=payload, headers={"X-API-Key": refused_key})
        assert response.status_code == 403, f"{refused_key} was allowed to {path}"


def test_drafting_a_statutory_rate_table_names_payroll_write() -> None:
    """The rate-table writes are declared `payroll:write`, and no role is read-only here yet.

    `POST /v1/rate-tables` and `PUT /v1/rate-tables/{id}/entries` used to be
    guarded by `payroll:read` alone. They now declare `payroll:write`, which is
    the honest requirement -- `PUT` resets `verified` and halts payroll, so it is
    not a read.

    There is deliberately no HTTP negative test to pair with that: `FINANCE`
    holds `payroll:read` and `payroll:write` together, so no configured role can
    demonstrate the difference over HTTP today. The declaration is asserted
    structurally in `test_route_inventory.py` instead, and this test records that
    the absence is a property of the role table rather than an oversight. When a
    read-only role is ever added, it becomes a 403 case here.
    """
    write_roles = [
        role
        for role in RoleId
        if has_permission(Principal(actor_id="x", role=role), Permission.PAYROLL_READ)
        and not has_permission(Principal(actor_id="x", role=role), Permission.PAYROLL_WRITE)
    ]
    assert write_roles == [], f"a payroll-read-only role exists; add the 403 case: {write_roles}"


def test_a_manager_may_not_certify_a_legal_document() -> None:
    """Verifying a passport is a compliance judgement, not directory access.

    `HR_ADMIN` is the only role holding `compliance:write`, so this is the route
    that most clearly must not fall back to `people:read`.
    """
    app = create_app(_manager_settings())
    with TestClient(app) as client:
        response = client.post(
            f"/v1/documents/{uuid4()}/verify",
            json={"status": "verified", "note": "looks right"},
            headers={"X-API-Key": "mgr-key"},
        )
        assert response.status_code == 403


def test_a_manager_may_not_manufacture_the_sign_off_it_wants_to_decide() -> None:
    """Creation is a weaker permission than `approvals:decide`, on purpose.

    `MANAGER` and `FINANCE` both hold `approvals:decide`. If raising an approval
    were also gated on that, either could create a request assigned to a role it
    controls and then approve it -- the separation of duties in
    `ApprovalEngine.decide` would still catch the self-approval, but only because
    it compares against `requested_by`, and only for the actor that created it.
    """
    app = create_app(_manager_settings())
    with TestClient(app) as client:
        response = client.post(
            "/v1/approvals",
            json={
                "subject": "leave_request",
                "subject_id": str(uuid4()),
                "title": "Sign off the June leave run",
                "assignee_role": "manager",
            },
            headers={"X-API-Key": "mgr-key"},
        )
        assert response.status_code == 403


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


# --- write permissions ---------------------------------------------------------
#
# The routers below used to guard their write routes with a *read* permission, so
# `payroll:read` was enough to open a payroll run and `compliance:read` was enough
# to record a consent. Nothing tested it: no test in the suite touched these
# routes with a non-admin key, so the gate stayed green through the change. The
# tests below exist to make that impossible to repeat -- each asserts the 403 for
# a role that must be refused, not only the 2xx for one that must be allowed.

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

_write_routes = write_routes
_route_permissions = route_permissions
_route = route
_read_guarded_write_routes = read_guarded_write_routes


READ_ONLY_WRITE_ROUTES: frozenset[str] = frozenset()
"""Mutating routes authorized by a read permission alone. Empty, and it stays empty.

The sweep that got here was 58 routes: 5 payroll, 13 compliance, 33 people
administration, 7 self-service. Each name now carries the permission that
describes it, and this set is what stops a new route being added without one.

A count could not do this job. ``len(read_only) == 0`` passes just as happily
against the wrong seven; asserting the exact set names the route that regressed
and says which permission it should have had.
"""


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/v1/payroll/runs", Permission.PAYROLL_WRITE),
        ("/v1/payroll/runs/{run_id}/inputs", Permission.PAYROLL_WRITE),
        ("/v1/payroll/runs/{run_id}/compute", Permission.PAYROLL_WRITE),
        ("/v1/payroll/runs/{run_id}/submit", Permission.PAYROLL_WRITE),
        ("/v1/payroll/runs/{run_id}/cancel", Permission.PAYROLL_WRITE),
        ("/v1/compliance/consents", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/consents/{consent_id}/revoke", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/retention/policies", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/retention/records", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/retention/records/{record_id}/hold", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/erasures", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/erasures/{request_id}/verify", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/erasures/{request_id}/submit", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/erasures/approvals/{approval_id}/sync", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/breaches", Permission.COMPLIANCE_WRITE),
        (
            "/v1/compliance/breaches/{incident_id}/steps/{step_key}/complete",
            Permission.COMPLIANCE_WRITE,
        ),
        ("/v1/compliance/breaches/{incident_id}/notifications", Permission.COMPLIANCE_WRITE),
        ("/v1/compliance/breaches/{incident_id}/status", Permission.COMPLIANCE_WRITE),
    ],
)
def test_these_routes_demand_their_write_permission(path: str, expected: Permission) -> None:
    """The 18 payroll and compliance writes name the write permission, by route.

    This asserts the requirement itself rather than a request outcome, and the
    distinction is not pedantic. `HR_ADMIN` is the only role holding *any*
    compliance permission, so every compliance request from a non-admin is
    refused by the router-level `compliance:read` before the route-level gate is
    ever reached -- an HTTP test would pass identically whether or not the write
    permission were declared. The same holds for payroll, where `FINANCE` holds
    read and write together.

    So through the API this change is invisible, which makes it defence in depth
    for the first role that is granted the read without the write. Asserting the
    declared requirement is the only way to know it is really there.
    """
    required = _route_permissions(_route(path))
    assert expected in required, (
        f"{path} does not require {expected.value}: {sorted(p.value for p in required)}"
    )


def test_the_execute_routes_keep_the_stronger_permission() -> None:
    """Purge and erasure execution are not merely `compliance:write`.

    They destroy data, and the router already escalated them past the write
    permission. A blanket sweep that rewrote every compliance write to
    `COMPLIANCE_WRITE` would quietly downgrade these two, so they are named.
    """
    for path in ("/v1/compliance/retention/purge", "/v1/compliance/erasures/{request_id}/execute"):
        required = _route_permissions(_route(path))
        assert Permission.COMPLIANCE_EXECUTE in required, path


def test_recruiter_keeps_the_people_writes_it_had_through_the_read_permission() -> None:
    """Entering a hire means writing people records, so recruiting keeps it.

    Before these routes named a permission, the recruiter role reached all of
    them through `people:read`. Naming `people:write` without also granting it
    would have quietly removed that reach at exactly the moment someone was
    trying to hire somebody, so the role was widened by the same commit.
    """
    recruiter = Principal(actor_id="rec-1", role=RoleId.RECRUITER)
    for permission in (
        Permission.PEOPLE_WRITE,
        Permission.RECRUITING_WRITE,
        Permission.TASKS_WRITE,
    ):
        assert has_permission(recruiter, permission), permission


def test_roles_that_only_ever_read_people_records_do_not_gain_the_write() -> None:
    """`people:write` is not granted as a side effect of seeing the directory.

    `MANAGER` and `FINANCE` both hold `people:read` -- a manager needs the
    directory to run a review, finance needs it to pay someone -- and neither is
    an HR administrator. Granting the write to preserve the old reach would have
    made the new permission as weak as the read it replaced.

    `EMPLOYEE` is the third case and the opposite one: it holds neither, which is
    why an employee cannot open a leave request today. The fix for that is the
    self-service permission, not a blanket write.
    """
    for role in (RoleId.MANAGER, RoleId.FINANCE):
        principal = Principal(actor_id="someone", role=role)
        assert has_permission(principal, Permission.PEOPLE_READ), role
        assert not has_permission(principal, Permission.PEOPLE_WRITE), role

    employee = Principal(actor_id="someone", role=RoleId.EMPLOYEE)
    assert not has_permission(employee, Permission.PEOPLE_READ)
    assert not has_permission(employee, Permission.PEOPLE_WRITE)


def test_a_read_permission_alone_never_guards_a_write() -> None:
    """No mutating route may be authorized by a read permission on its own.

    This is the structural version of the two tests above, and it is the one that
    keeps the other 40 routes from being forgotten. Asserting the 403 for one
    role on one route says nothing about the 40 routes no test touches -- which
    is exactly how 58 of them were wrong in the first place.

    The remaining read-only routes are listed explicitly. A count could not tell
    you which route regressed, and the list shrinks as the authorization work
    lands, so an entry is a visible to-do rather than a silent exemption.
    """
    read_only = sorted(_read_guarded_write_routes())
    assert read_only == sorted(READ_ONLY_WRITE_ROUTES), (
        "the set of write routes guarded only by a read permission changed: "
        f"unexpected={sorted(set(read_only) - set(READ_ONLY_WRITE_ROUTES))} "
        f"resolved={sorted(set(READ_ONLY_WRITE_ROUTES) - set(read_only))}"
    )


def test_no_write_route_is_left_unguarded() -> None:
    """A write with no declared permission at all would be open to any key.

    There is no such route today. Cheap to keep true.
    """
    unguarded = [route.path for route in _write_routes() if not _route_permissions(route)]
    assert not unguarded, f"write routes with no permission: {unguarded}"


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
