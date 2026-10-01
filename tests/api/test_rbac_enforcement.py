"""API-level RBAC: role-bound keys gate router access."""

import importlib
import pkgutil
from datetime import date
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.api import routers
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import Permission, RoleId


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


def _write_routes() -> list[APIRoute]:
    """Every mutating route, from the routers rather than from ``app.routes``.

    See ``tests/test_audit_provenance.py`` for why the included-router wrapper
    this FastAPI version builds is not a usable place to look.
    """
    routes: list[APIRoute] = []
    for module in pkgutil.iter_modules(routers.__path__):
        loaded = importlib.import_module(f"{routers.__name__}.{module.name}")
        router = getattr(loaded, "router", None)
        if router is None:
            continue
        routes.extend(
            route
            for route in router.routes
            if hasattr(route, "methods") and route.methods & WRITE_METHODS
        )
    return routes


def _route_permissions(route: APIRoute) -> set[Permission]:
    """The permissions a route requires, router-level ones included.

    ``require_permission`` closes over its ``Permission``, so the value is read
    out of the closure cell. That is reaching into an implementation detail, but
    it is the only place the requirement is recorded -- FastAPI does not expose
    it, and reading the closure is strictly better than asserting a count.
    """
    required: set[Permission] = set()
    for dependency in list(getattr(route, "dependencies", None) or []):
        closure = getattr(getattr(dependency, "dependency", None), "__closure__", None)
        for cell in closure or ():
            if isinstance(cell.cell_contents, Permission):
                required.add(cell.cell_contents)
    return required


def _route(path: str) -> APIRoute:
    """The one route with this path, or a failure naming what was found."""
    matches = [route for route in _write_routes() if route.path == path]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one write route at {path}, found {len(matches)}")
    return matches[0]


def _read_guarded_write_routes() -> set[str]:
    return {
        route.path
        for route in _write_routes()
        if _route_permissions(route)
        and all(p.value.endswith(":read") for p in _route_permissions(route))
    }


READ_ONLY_WRITE_ROUTES = frozenset(
    {
        # Growth: cycle administration, review assignments, summary drafting and
        # finalization, and goals. Left for the people-permission pass, which
        # also decides which of these are self-service.
        "/v1/growth/cycles",
        "/v1/growth/cycles/{cycle_id}/activate",
        "/v1/growth/cycles/{cycle_id}/reviewing",
        "/v1/growth/cycles/{cycle_id}/close",
        "/v1/growth/cycles/{cycle_id}/cancel",
        "/v1/growth/cycles/{cycle_id}/assignments",
        "/v1/growth/assignments/{assignment_id}/submit",
        "/v1/growth/assignments/{assignment_id}/skip",
        "/v1/growth/summaries",
        "/v1/growth/summaries/{summary_id}/finalize",
        "/v1/growth/goals",
        "/v1/growth/goals/{goal_id}/activate",
        "/v1/growth/goals/{goal_id}/progress",
        "/v1/growth/goals/{goal_id}/complete",
        "/v1/growth/goals/{goal_id}/cancel",
        "/v1/growth/reminders/run",
        # Leave: policy and calendar administration, balance adjustments, request
        # submission, cancellation, and the approval sync.
        "/v1/leave/policies",
        "/v1/leave/calendar/holidays",
        "/v1/leave/balances/{employee_id}/{leave_type}/adjust",
        "/v1/leave",
        "/v1/leave/requests/{request_id}/cancel",
        "/v1/leave/approvals/{approval_id}/sync",
        # Onboarding and offboarding: templates, plans, assets and step
        # transitions.
        "/v1/onboarding/templates",
        "/v1/onboarding/plans",
        "/v1/onboarding/plans/{plan_id}/steps/{step_key}/complete",
        "/v1/onboarding/plans/{plan_id}/steps/{step_key}/waive",
        "/v1/onboarding/plans/{plan_id}/steps/{step_key}/link-document",
        "/v1/offboarding/templates",
        "/v1/offboarding/plans",
        "/v1/offboarding/plans/{plan_id}/steps/{step_key}/complete",
        "/v1/offboarding/plans/{plan_id}/steps/{step_key}/waive",
        "/v1/offboarding/plans/{plan_id}/exit-interview",
        "/v1/offboarding/plans/{plan_id}/handover",
        "/v1/offboarding/plans/{plan_id}/final-pay",
        "/v1/offboarding/plans/{plan_id}/complete",
        "/v1/offboarding/plans/{plan_id}/finalize-employee",
        "/v1/offboarding/assets",
        "/v1/offboarding/assets/{asset_id}/return",
        "/v1/offboarding/assets/{asset_id}/missing",
        "/v1/offboarding/assets/{asset_id}/write-off",
    }
)
"""Mutating routes still authorized by a read permission alone.

Payroll and compliance are no longer in this list. Every entry here is tracked
work: each one is waiting on the people-permission pass to decide whether it is
HR administration (``people:write``) or the caller's own business
(``self_service``). Deleting an entry is how that pass records its progress."""


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
