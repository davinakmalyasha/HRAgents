"""The typed error contract.

The API answered with ``application/problem+json`` before this, but every response carried
``"type": "about:blank"`` and no code, so a client could only tell errors apart by reading
English prose. Twenty-five router sites branched on that prose to choose a status code,
which means rewording one exception message could silently move a 409 to a 403 -- and two
comments in the routers record that it already happened twice.

These tests pin the contract a client can now rely on:

- ``code`` is a stable machine-readable discriminator.
- ``type`` is a stable URI derived from it.
- ``title`` is still the prose, unchanged, so nothing a human reads regressed.
- ``RequestValidationError`` is finally a problem document, and its ``detail`` is still the
  per-field *list* fourteen other tests assert.
- 401 and 403 carry different codes, and "not a named human" is distinct from "your role
  may not do this" -- two failures that previously looked identical to a client and were
  given the same translation key.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Protocol

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hr_agents.api.problem import (
    PROBLEM_BASE_URI,
    ApiProblem,
    ProblemCode,
    conflict,
    forbidden,
    not_found,
    problem_uri,
)
from hr_agents.main import create_app

PROBLEM = "application/problem+json"


@contextmanager
def make_client() -> Iterator[TestClient]:
    """A client on the real app, so the registered handlers are the ones under test."""
    with TestClient(create_app()) as client:
        yield client


class _HasProblem(Protocol):
    """The part of a response this file reads.

    Two copies of `httpx` are installed -- one under Starlette, one standalone -- so
    naming either concrete class here picks a side and fails on the other. The three
    members actually used are all a client can rely on.
    """

    status_code: int

    @property
    def headers(self) -> Any:
        """httpx.Headers, which is a case-insensitive mapping but not one."""
        ...

    def json(self) -> Any: ...


def _problem_of(response: _HasProblem) -> dict[str, Any]:
    assert response.headers["content-type"].startswith(PROBLEM), (
        f"expected {PROBLEM}, got {response.headers.get('content-type')}"
    )
    return response.json()


# --- the shape ---------------------------------------------------------------


def test_a_typed_error_carries_a_code_and_a_stable_type() -> None:
    from hr_agents.main import _problem_response

    app = FastAPI()
    app.add_exception_handler(ApiProblem, _problem_response)  # type: ignore[arg-type]

    @app.get("/boom")
    def boom() -> None:
        raise not_found("unknown employee 1234")

    body = _problem_of(TestClient(app, raise_server_exceptions=False).get("/boom"))

    assert body["code"] == ProblemCode.UNKNOWN_RECORD.value
    assert body["type"] == f"{PROBLEM_BASE_URI}/unknown_record"
    assert body["status"] == 404
    assert body["title"] == "unknown employee 1234"
    # `detail` is additive: `title` was already the prose and is unchanged.
    assert body["detail"] == "unknown employee 1234"
    assert body["instance"] == "/boom"


def test_the_type_uri_is_namespaced_and_stable() -> None:
    assert problem_uri(ProblemCode.CONFLICT) == f"{PROBLEM_BASE_URI}/conflict"
    for code in ProblemCode:
        assert problem_uri(code).startswith(f"{PROBLEM_BASE_URI}/")


def test_an_untyped_http_exception_still_produces_a_valid_problem() -> None:
    """A bare `HTTPException` has no code, so it keeps RFC 7807's `about:blank`.

    Returning `about:blank` rather than inventing a code is the honest answer: we do not
    describe that one yet, and the client can tell "described" from "not".
    """
    from fastapi import HTTPException, status

    from hr_agents.main import _problem_response

    app = FastAPI()
    app.add_exception_handler(HTTPException, _problem_response)  # type: ignore[arg-type]

    @app.get("/plain")
    def plain() -> None:
        raise HTTPException(status_code=status.HTTP_418_IM_A_TEAPOT, detail="teapot")

    body = _problem_of(TestClient(app, raise_server_exceptions=False).get("/plain"))

    assert body["type"] == "about:blank"
    assert body["code"] is None
    assert body["title"] == "teapot"


def test_api_problem_is_an_http_exception_so_existing_handlers_keep_working() -> None:
    """Every existing `except HTTPException` must still catch a typed problem."""
    from fastapi import HTTPException

    err = conflict("already exists", code=ProblemCode.STATE_CONFLICT)
    assert isinstance(err, HTTPException)
    assert err.status_code == 409
    assert isinstance(err, ApiProblem)
    assert err.code is ProblemCode.STATE_CONFLICT


# --- the case this exists for -------------------------------------------------


def test_a_refusal_to_an_agent_is_not_reported_as_a_role_permission_problem() -> None:
    """Two different diagnoses that used to be indistinguishable.

    An agent calling a named-human-only endpoint was told the same thing as a manager
    calling an endpoint they lack permission for -- same shape, same `type`, same
    translation key. The client's instruction differs completely: one needs a person, the
    other needs a different key.
    """
    role = forbidden("role manager lacks permission payroll:approve")
    human = forbidden("only a named human may sign this off", code=ProblemCode.NAMED_HUMAN_REQUIRED)

    assert role.code is ProblemCode.PERMISSION_DENIED
    assert human.code is ProblemCode.NAMED_HUMAN_REQUIRED
    assert role.type_uri != human.type_uri


def test_a_missing_and_a_refused_credential_are_different_codes() -> None:
    from hr_agents.api.problem import problem

    missing = problem(401, ProblemCode.AUTH_REQUIRED, "authentication required")
    refused = problem(401, ProblemCode.AUTH_INVALID, "invalid or missing API key")

    assert missing.code is ProblemCode.AUTH_REQUIRED
    assert refused.code is ProblemCode.AUTH_INVALID


def test_a_refused_credential_carries_the_auth_code() -> None:
    """A 401 must say *which* authentication failure it was.

    `test_auth_middleware.py` already asserts 401 and 403 differ by status. This asserts
    the body distinguishes them too, because status alone cannot tell the seven domain
    403s from the RBAC 403 -- and cannot tell a missing key from a refused one.
    """
    with make_client() as client:
        response = client.get("/v1/jobs", headers={"X-API-Key": "not-a-real-key"})
        if response.status_code != 401:
            pytest.skip("authentication is disabled in this configuration")
        assert _problem_of(response)["code"] == ProblemCode.AUTH_INVALID.value


# --- validation errors --------------------------------------------------------


def test_a_schema_violation_is_a_problem_document() -> None:
    """FastAPI's 422 used to be served as plain `application/json`.

    It was the only structured error the API produced and the only one that was not a
    problem document. Fourteen tests assert `detail` is the per-field list, so the list is
    preserved; the envelope around it is now the project's.
    """
    with make_client() as client:
        response = client.post("/v1/jobs", json={"title": ""})
        body = _problem_of(response)

    assert response.status_code == 422
    assert body["code"] == ProblemCode.VALIDATION_FAILED.value
    assert body["type"] == f"{PROBLEM_BASE_URI}/validation_failed"
    assert body["status"] == 422
    assert isinstance(body["detail"], list)
    assert body["detail"], "the per-field errors must survive"
    assert any("title" in str(error.get("loc", "")) for error in body["detail"])


def test_a_rejected_actor_field_still_reports_the_field_by_name() -> None:
    """The regression guard for the fourteen `detail`-is-a-list assertions.

    Sending a body that names the actor must still produce a 422 naming the field --
    that gate is the point of it, and it must not be flattened into a generic message.
    """
    with make_client() as client:
        response = client.post("/v1/jobs", json={"title": "Backend", "by": "someone"})
        body = _problem_of(response)

    assert response.status_code == 422
    assert any(error["loc"][-1] == "by" for error in body["detail"])


# --- the helpers --------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "expected_status", "expected_code"),
    [
        (lambda: not_found("unknown thing"), 404, ProblemCode.UNKNOWN_RECORD),
        (lambda: conflict("already decided"), 409, ProblemCode.STATE_CONFLICT),
        (lambda: forbidden("no"), 403, ProblemCode.PERMISSION_DENIED),
    ],
)
def test_the_shared_helpers_carry_their_default_code(
    factory: Callable[[], ApiProblem], expected_status: int, expected_code: ProblemCode
) -> None:
    err = factory()
    assert err.status_code == expected_status
    assert err.code is expected_code


def test_a_caught_domain_error_can_be_passed_straight_through() -> None:
    """`_conflict(exc)` took an Exception; the shared `conflict()` still does."""
    err = conflict(ValueError("something went wrong in the service"))
    assert err.status_code == 409
    assert "something went wrong in the service" in err.detail


# --- the ASGI middleware ------------------------------------------------------


def test_an_oversized_body_is_a_problem_document() -> None:
    """413 used to send the same keys as `application/json`.

    A client that branched on the problem media type therefore treated an oversized
    upload as a successful response.
    """
    from fastapi import FastAPI

    from hr_agents.api.hardening import BodySizeLimitMiddleware

    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=64)

    @app.post("/upload")
    def upload() -> dict[str, bool]:
        return {"ok": True}

    response = TestClient(app).post("/upload", content=b"x" * 512)
    body = _problem_of(response)

    assert response.status_code == 413
    assert body["code"] == ProblemCode.PAYLOAD_TOO_LARGE.value
    assert body["type"] == f"{PROBLEM_BASE_URI}/payload_too_large"


def test_the_problem_model_documents_the_contract() -> None:
    """`ProblemDetail` exists so the OpenAPI document describes the error shape.

    Without a declared response model, the generated client has no idea a `code` exists.
    """
    from hr_agents.api.problem import ProblemDetail

    fields = ProblemDetail.model_fields
    assert {"type", "title", "status", "detail", "instance", "code"} <= set(fields)
