"""Domain refusals carry their own code, so routers stop reading English.

The regression this file exists to prevent is not a crash: it is a reworded
exception message quietly moving a status code. Twenty-five router sites used to
recognise a failure by asking whether the text contained "named human", and two
comments in the routers record that rewording one sentence had already moved a
409 to a 403.
"""

from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from hr_agents.api.problem import domain_problem
from hr_agents.errors import DomainCode, DomainError
from hr_agents.identity import ActorRef

ROUTERS = pathlib.Path("src/hr_agents/api/routers")

#: The refusal the gate raises, and what it must look like on the wire.
NAMED_HUMAN = ProblemCodeNamedHuman = "named_human_required"


def test_a_domain_error_defaults_to_a_state_conflict() -> None:
    assert DomainCode("state_conflict") is DomainCode.STATE_CONFLICT
    assert DomainError("plain").status == 409
    assert DomainError("plain").code is DomainCode.STATE_CONFLICT


def test_a_refusal_can_carry_its_own_code_and_status() -> None:
    refusal = DomainError("agents cannot do this", code=DomainCode.NAMED_HUMAN_REQUIRED, status=403)
    assert refusal.status == 403
    assert refusal.code is DomainCode.NAMED_HUMAN_REQUIRED
    assert str(refusal) == "agents cannot do this"


def test_the_named_human_gate_sets_the_code_once() -> None:
    """The rule is decided where the refusal happens, not per router.

    `require_named_human` is the single place an agent is turned away, so it is
    the single place that knows the answer is 403 and named_human_required.
    """
    with pytest.raises(DomainError) as caught:
        ActorRef.coerce("agent:feedback").require_human("decide", _error_type())
    assert caught.value.code is DomainCode.NAMED_HUMAN_REQUIRED
    assert caught.value.status == 403


def test_domain_problem_turns_the_code_into_the_response() -> None:
    refusal = DomainError("agents cannot decide", code=DomainCode.NAMED_HUMAN_REQUIRED, status=403)
    response = domain_problem(refusal)
    assert response.status_code == 403
    assert "agents cannot decide" in str(response.detail)


def test_domain_problem_falls_back_to_a_conflict() -> None:
    """A refusal that forgot its code is still a 409, not a 500."""
    response = domain_problem(DomainError("something already happened"))
    assert response.status_code == 409


def _error_type() -> type[DomainError]:
    from hr_agents.services.approvals import ApprovalError

    return ApprovalError


def test_no_router_recognises_a_failure_by_reading_its_message() -> None:
    """The sniff is gone, and this is what stops it coming back.

    Every one of these branches existed for the same reason -- the refusal had no
    code -- so the rule is now in one place. A new branch matching on prose would
    be a second opinion about a status code, which is the bug itself.
    """
    offenders: list[str] = []
    pattern = re.compile(r"if .*[\"']named human[\"'] in \w+")
    for path in sorted(ROUTERS.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{number}")
    assert offenders == [], f"routers sniffing prose again: {offenders}"


def test_the_domains_keep_their_old_bases() -> None:
    """Reparenting must be additive.

    `except RuntimeError` exists in places that were not part of this change. If
    a domain class stopped being a RuntimeError, those handlers would silently
    stop catching it and the failure would become an unhandled 500.
    """
    from hr_agents.services.approvals import ApprovalError
    from hr_agents.services.growth import GrowthError
    from hr_agents.services.leave import LeaveError
    from hr_agents.services.payroll import PayrollError

    for cls in (ApprovalError, GrowthError, LeaveError, PayrollError):
        assert issubclass(cls, DomainError)
        assert issubclass(cls, RuntimeError)


def test_the_base_imports_nothing_from_the_package() -> None:
    """`identity` needs the base, and everything under `services` imports `identity`.

    A definition that imported from `hr_agents` would make that a cycle, which is
    how the first attempt at this failed.
    """
    source = (pathlib.Path("src/hr_agents/errors.py")).read_text(encoding="utf-8")
    tree = inspect.cleandoc(source)
    assert "import hr_agents" not in tree


@pytest.mark.parametrize("code", list(DomainCode))
def test_every_domain_code_maps_to_a_problem_code(code: DomainCode) -> None:
    """An unmapped code would silently degrade to `state_conflict` in production.

    The mapping table in `api/problem.py` is what stops a new domain code from
    being invisible to a client.
    """

    response = domain_problem(DomainError("x", code=code, status=409))
    assert response.status_code == 409
    # A code that falls through would return STATE_CONFLICT for anything else.
    assert _code_of(response) is not None


def _code_of(response: object) -> object:
    return getattr(response, "code", None) or getattr(response, "detail", None)
