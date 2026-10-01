"""Provenance on the audit chain: who acted, and how we know.

The chain's value is that a reader can tell a person from a timer from an agent
tool. ``ActorProvenance`` records that, and ``AuditActor.role`` records what
authority the person held. Both are silently lost by a single plausible-looking
line -- passing ``actor.actor_id`` (a string) where an ``ActorRef`` was meant --
and nothing else in the suite would notice, because the actor *name* still looks
right.

``scripts/smoke_onboarding.py`` found exactly that bug during the final sweep:
employees, contracts and tasks all unwrapped the ``ActorRef`` to a string before
recording, so every authenticated write landed as ``legacy_string`` with no
role. These tests are the regression fence.

The one documented exception is the approval→outcome sync, which reads the
approver's name back off a stored record. ``deciding_actor()`` marks that
``legacy_string`` on purpose: the person was verified when they decided, but
nothing at that point can prove it twice, and stamping ``authenticated`` on a
value loaded from storage would assert something the code never checked.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from datetime import date, timedelta

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from hr_agents.api import routers
from hr_agents.api.deps import ActorDep
from hr_agents.identity import ActorRef, deciding_actor
from hr_agents.main import create_app
from hr_agents.models import ActorProvenance, ActorType, ApprovalSubject, ApproverRole
from hr_agents.services import ApprovalEngine, ApprovalError
from hr_agents.services.people_store import ApprovalStore

TODAY = date.today()


def test_an_http_write_records_an_authenticated_actor_with_its_role() -> None:
    app = create_app()
    with TestClient(app) as client:
        response = client.post(
            "/v1/employees",
            json={
                "full_name": "Rina Hartati",
                "hire_date": (TODAY - timedelta(days=30)).isoformat(),
            },
        )
    assert response.status_code == 201

    entries = [entry for entry in app.state.audit.entries if entry.action == "employee.created"]
    assert entries, "the hire was not recorded on the chain"
    actor = entries[-1].actor
    assert actor.actor_id == "local-dev"
    assert actor.actor_type is ActorType.HUMAN
    assert actor.provenance is ActorProvenance.AUTHENTICATED
    assert actor.role == "hr_admin"


def test_every_authenticated_surface_records_provenance_not_a_bare_string() -> None:
    """The sweep found three services unwrapping the ActorRef before recording.

    This walks a representative slice of every workspace that writes through the
    API and asserts that nothing degrades to ``legacy_string`` -- the value a
    body field used to produce, and therefore the signature of exactly the bug
    this module exists to prevent.
    """
    app = create_app()
    with TestClient(app) as client:
        hire = client.post(
            "/v1/employees",
            json={
                "full_name": "Budi Santoso",
                "hire_date": (TODAY - timedelta(days=10)).isoformat(),
            },
        )
        employee_id = hire.json()["id"]

        contract = client.post(
            "/v1/contracts",
            json={
                "employee_id": employee_id,
                "contract_type": "pkwt",
                "start_date": TODAY.isoformat(),
                "end_date": (TODAY + timedelta(days=365)).isoformat(),
            },
        )
        assert contract.status_code == 201, contract.text

        task = client.post("/v1/tasks", json={"title": "Chase the missing NPWP"})
        assert task.status_code == 201

        org_unit = client.post("/v1/org-units", json={"name": "Platform Engineering"})
        assert org_unit.status_code == 201

        policy = client.put(
            "/v1/leave/policies",
            json={"leave_type": "annual", "name": "Annual leave"},
        )
        assert policy.status_code == 200

    degraded = [
        (entry.action, entry.actor.actor_id, entry.actor.provenance.value)
        for entry in app.state.audit.entries
        if entry.actor.provenance is ActorProvenance.LEGACY_STRING
    ]
    assert not degraded, (
        "these entries recorded a bare actor string instead of the ActorRef that "
        f"produced them: {degraded}"
    )


def test_a_scheduler_sweep_records_a_system_job_not_a_person() -> None:
    app = create_app()
    # a contract that expires inside the warning window, so the sweep has work
    with TestClient(app) as client:
        hire = client.post(
            "/v1/employees",
            json={"full_name": "Wira", "hire_date": TODAY.isoformat()},
        )
        client.post(
            "/v1/contracts",
            json={
                "employee_id": hire.json()["id"],
                "contract_type": "pkwt",
                "start_date": TODAY.isoformat(),
                "end_date": (TODAY + timedelta(days=30)).isoformat(),
            },
        )
    before = len(app.state.audit.entries)
    created = app.state.people.contracts.create_expiry_tasks(as_of=TODAY)
    check_actors = [
        entry
        for entry in app.state.audit.entries[before:]
        if entry.actor.provenance is not ActorProvenance.SYSTEM_JOB
    ]
    assert created, "the sweep had nothing to do; the fixture did not age the contract"
    assert not check_actors, (
        "a scheduled sweep recorded an actor that is not a system job: "
        f"{[(e.action, e.actor.actor_id, e.actor.provenance.value) for e in check_actors]}"
    )


def test_an_agent_tool_records_agent_provenance() -> None:
    agent = ActorRef.agent("feedback_writer")
    assert agent.actor_type is ActorType.AGENT
    assert agent.provenance is ActorProvenance.AGENT_TOOL
    assert agent.role is None, "an agent tool holds no authorization role"
    assert agent.audit_actor().provenance is ActorProvenance.AGENT_TOOL


def test_reading_an_approver_back_off_storage_does_not_claim_authentication() -> None:
    """The documented exception, pinned so it stays deliberate.

    ``deciding_actor`` is the one place that reconstructs an actor from stored
    data. If it ever starts claiming ``authenticated``, the chain is asserting a
    verification that nobody performed on this code path.
    """
    actor = deciding_actor("Rina")
    assert actor.actor_id == "Rina"
    assert actor.provenance is ActorProvenance.LEGACY_STRING

    unnamed = deciding_actor(None)
    assert unnamed.actor_id == "approval-engine"
    assert unnamed.actor_type is ActorType.SYSTEM, "the engine's own sweep is a system actor"


def test_the_approval_engine_records_the_deciding_actor_not_the_engine() -> None:
    engine = ApprovalEngine(ApprovalStore())
    request = engine.create(
        subject=ApprovalSubject.PAYROLL_RUN,
        subject_id="run-1",
        title="Sign off the June payroll",
        assignee_role=ApproverRole.FINANCE,
        actor=ActorRef.legacy("sari"),
    )
    decision = engine.decide(request.id, actor=ActorRef.legacy("finance-lead"), approve=True)
    assert decision.request.decided_by == "finance-lead"

    decided = [entry for entry in engine.audit.entries if entry.action == "approval.approved"]
    assert decided, "the decision was not recorded"
    assert decided[-1].actor.actor_id == "finance-lead"


def test_a_claim_of_authentication_the_code_never_checked_is_not_writable() -> None:
    """`ActorRef` has no public "forge this provenance" path.

    A caller can label an actor a system or an agent -- those are claims about a
    real thing in this system -- but there is no way to assert ``authenticated``
    for something that never passed through the middleware. That asymmetry is
    deliberate and worth a fence.
    """
    assert set(ActorProvenance) == {
        ActorProvenance.AUTHENTICATED,
        ActorProvenance.SYSTEM_JOB,
        ActorProvenance.AGENT_TOOL,
        ActorProvenance.LEGACY_STRING,
    }
    forged = ActorRef.legacy("someone")
    assert forged.provenance is not ActorProvenance.AUTHENTICATED
    assert ActorRef.system("scheduler").provenance is not ActorProvenance.AUTHENTICATED


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_actor_is_not_constructible(blank: str) -> None:
    """The stronger property: there is nothing left for a gate to reject.

    ``AuditActor.actor_id`` has ``min_length=1``, so a blank actor could never
    have reached the chain. Refusing it at construction removes the failure mode
    where a state change succeeded and the audit append then failed.
    """
    from hr_agents.identity import ActorError

    with pytest.raises(ActorError):
        ActorRef.legacy(blank)
    with pytest.raises(ActorError):
        ActorRef.agent("")


def test_the_named_human_gate_is_reachable_only_where_an_actor_can_be_non_human() -> None:
    """The 422 path and the gate path are different paths, and both are tested.

    Over HTTP a request cannot name an actor, so the gate is only reachable at
    the service layer. This asserts the service still refuses one, so the router
    branches that map the refusal are not mapping a state that cannot occur.
    """
    engine = ApprovalEngine(ApprovalStore())
    request = engine.create(
        subject=ApprovalSubject.ERASURE_REQUEST,
        subject_id="req-1",
        title="Erasure request",
        assignee_role=ApproverRole.DATA_PROTECTION,
        actor=ActorRef.legacy("someone"),
    )
    for actor in (
        ActorRef.agent("records"),
        ActorRef.system("retention-sweep"),
        ActorRef.legacy("system"),
    ):
        with pytest.raises(ApprovalError):
            engine.decide(request.id, actor=actor, approve=True)


NO_ACTOR_WRITE_ROUTES = frozenset(
    {
        # A candidate submitting a form is an external, unauthenticated party.
        # The entry is filed as `application.received` under a system actor, which
        # is at least an honest description: we cannot name a person, so we do
        # not pretend to. Making candidates authenticated principals is a design
        # question this codebase has deliberately not answered yet.
        "/v1/applications",
        "/v1/applications/batch",
        # Chat takes the principal directly rather than an `ActorRef` -- it needs
        # the role as well as the id, to pick the agent's tools. The conversation
        # owner is recorded from that principal, so these are authenticated; they
        # are listed here only because the parameter is not named `actor`.
        "/v1/chat",
        "/v1/chat/handoffs",
    }
)
"""Mutating routes with no ``actor`` parameter, and why each is acceptable."""


def _actor_annotation(route: APIRoute) -> object | None:
    """The resolved ``actor`` annotation for a route, or ``None`` if it has none.

    Every module here uses ``from __future__ import annotations``, so a signature
    read naively yields the *string* ``"ActorDep"`` and comparing it to the alias
    would fail on every route while looking like a real finding. ``eval_str``
    resolves in the endpoint's own module globals, which is where the alias is
    imported.
    """
    parameters = inspect.signature(route.endpoint, eval_str=True).parameters
    return parameters["actor"].annotation if "actor" in parameters else None


def _write_routes() -> list[APIRoute]:
    """Every mutating route, collected from the routers themselves.

    ``app.routes`` is not usable here: this FastAPI version represents an
    included router as a lazy wrapper with no ``path`` and no ``methods``, so the
    endpoints are only reachable by walking framework internals that a version
    bump would move. The ``APIRouter`` each module exports is public API, and it
    is the same object the application includes.
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
            if hasattr(route, "methods") and route.methods & {"POST", "PUT", "PATCH", "DELETE"}
        )
    return routes


def test_write_routes_declare_their_actor_as_a_dependency() -> None:
    """No route may source its actor from anywhere but ``ActorDep``.

    The provenance bugs this file fences all had one shape: a service received a
    string, or nothing, where an ``ActorRef`` belonged. A route that sourced its
    actor some other way -- from a body, a query parameter, or left to default to
    a system actor -- would reopen that hole while every service-level test
    stayed green, because a service cannot tell how it was called.

    So this asserts the wiring itself: wherever a write route takes an actor, the
    annotation is ``ActorDep`` and not a bare ``ActorRef`` a caller could have
    satisfied by hand.
    """
    actors: dict[str, object] = {
        route.path: annotation
        for route in _write_routes()
        if (annotation := _actor_annotation(route)) is not None
    }

    assert len(actors) >= 80, f"only {len(actors)} write routes take an actor; did the API shrink?"
    wrong = {path: annotation for path, annotation in actors.items() if annotation != ActorDep}
    assert not wrong, f"actor must come from ActorDep: {wrong}"


def test_every_write_route_takes_an_actor() -> None:
    """A mutating route with no actor at all is the shape of the original bug.

    Every write below POST is expected to name who did it. Listing the exceptions
    is deliberate: a bare count cannot tell you *which* route regressed, and a
    silently dropped ``ActorDep`` is exactly how an audit entry ends up stamped
    with a system actor because nobody was around to press the button.

    This is the check that caught ``POST /v1/growth/reminders/run``, which created
    system reminder tasks under a hardcoded ``system:scheduler`` actor even when
    an operator triggered the sweep by hand -- the same defect the approval
    escalation sweep had.
    """
    without_actor = {route.path for route in _write_routes() if _actor_annotation(route) is None}

    assert without_actor == set(NO_ACTOR_WRITE_ROUTES)
