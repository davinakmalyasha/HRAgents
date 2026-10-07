"""RFC 7807 problem details with a stable, machine-readable ``code``.

The API already answered with ``application/problem+json``, but every response had
``"type": "about:blank"`` and no code, so a client could only tell errors apart by reading
English prose. Twenty-seven router sites *themselves* branch on that prose --
``if message.startswith("unknown")``, ``if "named human" in message`` -- which means
rewording one exception message can silently move a status code from 409 to 403. Two
comments in the routers say exactly that this has already happened.

So the contract is additive and backwards compatible:

- ``type`` becomes a stable URI derived from ``code``, which is what RFC 7807 asks for
  and what a client can switch on.
- ``code`` is added, and it is the discriminator. ``web/src/lib/problem.ts`` already
  declares ``ProblemDetail.code`` and ships a ``matches()`` helper for it, currently with
  no call sites because the server never sent one.
- ``detail`` is added alongside ``title``. ``title`` stays the prose, unchanged, so the
  twenty-one API tests that assert on message wording keep passing.
- ``RequestValidationError`` is finally handled, and its ``detail`` stays the
  *list* FastAPI produced, because fourteen tests assert that shape.

What is deliberately not done here is replacing the prose sniffing in the routers. That
is mechanical follow-up work; this commit makes it *possible* by making ``code``
available, and every code below is chosen so a router can adopt it without changing what
a human reads.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

PROBLEM_MEDIA_TYPE = "application/problem+json"
"""The media type every error is served as, and the one `ERROR_RESPONSES` declares.

Kept here so the middleware, the exception handlers and the OpenAPI document cannot drift
into three different answers -- which is what happened: the 413 and 429 paths sent the
same keys as `application/json`.
"""

PROBLEM_BASE_URI = "https://hragents.dev/problems"
"""Namespace for ``type`` URIs.

Not dereferenceable on purpose. RFC 7807 says a ``type`` URI MAY be dereferenced, and a
documentation site that drifts out of step with the codes in this file would be worse than
a stable identifier that says only what it is.
"""


class ProblemCode(StrEnum):
    """Stable machine-readable error kinds.

    These are contract, not prose. Rename one and every client that switches on it breaks;
    so add a new one instead, and keep the retired value reserved.
    """

    # --- authentication and authorization -------------------------------
    AUTH_REQUIRED = "auth_required"
    """No credentials were presented."""
    AUTH_INVALID = "auth_invalid"
    """Credentials were presented and refused."""
    PERMISSION_DENIED = "permission_denied"
    """The role authenticated fine and is not allowed to do this."""
    NAMED_HUMAN_REQUIRED = "named_human_required"
    """The caller is authorized but is not a named human.

    Distinct from `PERMISSION_DENIED` on purpose: those two were previously the same
    shape and the same translation key, so a caller who was refused for not being a
    person was told their *role* could not do it.
    """

    # --- generic shapes ---------------------------------------------------
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    VALIDATION_FAILED = "validation_failed"
    """The request body did not satisfy the schema."""
    REASON_REQUIRED = "reason_required"
    """A consequential action was requested without the reason the domain demands."""
    PAYLOAD_TOO_LARGE = "payload_too_large"
    RATE_LIMITED = "rate_limited"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL = "internal"

    # --- domain refusals --------------------------------------------------
    UNKNOWN_RECORD = "unknown_record"
    """The referenced record does not exist.

    Replaces ``startswith("unknown ...")``, which returned 404 for an unknown record and
    nothing at all for anything else.
    """
    STATE_CONFLICT = "state_conflict"
    """The record exists but is not in a state that allows this."""
    INSUFFICIENT_BALANCE = "insufficient_balance"
    TEMPLATE_UNAVAILABLE = "template_unavailable"
    RATE_TABLE_UNUSABLE = "rate_table_unusable"
    BLOCKING_ANOMALIES = "blocking_anomalies"
    APPROVAL_ALREADY_DECIDED = "approval_already_decided"
    OWNERSHIP_REQUIRED = "ownership_required"
    WORKSPACE_MISMATCH = "workspace_mismatch"


class ProblemDetail(BaseModel):
    """The response body. Documents the contract in the OpenAPI document.

    ``detail`` is polymorphic and the annotation says so: a `RequestValidationError`
    problem carries a *list* of per-field errors there, which is what FastAPI produces and
    what fourteen tests assert. The annotation used to claim ``str | None`` while the
    runtime sent a list, so a generated client could only have handled it by being wrong.
    Switch on ``code`` rather than inspecting ``detail`` -- the shape is stable per code,
    but the codes are the contract.
    """

    type: str = Field(description="Stable URI identifying the error kind.")
    title: str = Field(description="A short human-readable summary of the problem.")
    status: int = Field(description="The HTTP status code.")
    detail: str | list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Explanation specific to this occurrence. A validation problem carries a "
            "list of per-field errors here rather than a string."
        ),
    )
    instance: str | None = Field(default=None, description="The path of the request.")
    code: ProblemCode | None = Field(
        default=None,
        description=(
            "Machine-readable error kind. Switch on this rather than on `title`, which "
            "is prose and may be reworded."
        ),
    )


def problem_uri(code: ProblemCode) -> str:
    """The ``type`` URI for a code."""
    return f"{PROBLEM_BASE_URI}/{code.value}"


class ApiProblem(HTTPException):
    """An ``HTTPException`` that also carries a `ProblemCode`.

    Subclasses ``HTTPException`` so every existing ``except HTTPException`` and every
    existing raise-site keeps working unchanged; the only difference is that the global
    handler can find a code to put in the body.
    """

    def __init__(
        self,
        status_code: int,
        code: ProblemCode,
        *,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code

    @property
    def type_uri(self) -> str:
        return problem_uri(self.code)


def problem(
    status_code: int,
    code: ProblemCode,
    detail: str,
    *,
    headers: dict[str, str] | None = None,
) -> ApiProblem:
    """Raise-ready typed problem.

    ```python
    if store.get(id) is None:
        raise problem(404, ProblemCode.UNKNOWN_RECORD, f"unknown employee {id}")
    ```
    """
    return ApiProblem(status_code, code, detail=detail, headers=headers)


# Each accepts str | Exception so a router can pass a caught domain error straight
# through, which is what the twenty-eight per-module _conflict(exc) copies did.
Message = str | Exception


def not_found(detail: Message, *, code: ProblemCode = ProblemCode.UNKNOWN_RECORD) -> ApiProblem:
    return problem(status.HTTP_404_NOT_FOUND, code, str(detail))


def conflict(detail: Message, *, code: ProblemCode = ProblemCode.STATE_CONFLICT) -> ApiProblem:
    return problem(status.HTTP_409_CONFLICT, code, str(detail))


def forbidden(detail: Message, *, code: ProblemCode = ProblemCode.PERMISSION_DENIED) -> ApiProblem:
    return problem(status.HTTP_403_FORBIDDEN, code, str(detail))


def bad_request(
    detail: Message, *, code: ProblemCode = ProblemCode.VALIDATION_FAILED
) -> ApiProblem:
    return problem(status.HTTP_400_BAD_REQUEST, code, str(detail))


def unprocessable(detail: str, *, code: ProblemCode = ProblemCode.REASON_REQUIRED) -> ApiProblem:
    return problem(status.HTTP_422_UNPROCESSABLE_CONTENT, code, detail)


def body_too_large(detail: str) -> ApiProblem:
    return problem(status.HTTP_413_CONTENT_TOO_LARGE, ProblemCode.PAYLOAD_TOO_LARGE, detail)


def too_many_requests(detail: str, *, retry_after: int) -> ApiProblem:
    return problem(
        status.HTTP_429_TOO_MANY_REQUESTS,
        ProblemCode.RATE_LIMITED,
        detail,
        headers={"Retry-After": str(retry_after)},
    )


def unavailable(detail: Message) -> ApiProblem:
    return problem(
        status.HTTP_503_SERVICE_UNAVAILABLE, ProblemCode.SERVICE_UNAVAILABLE, str(detail)
    )


def _documented(description: str, **extra: object) -> dict[str, object]:
    """One documented error response, under the media type we actually serve.

    Spelled with an explicit ``content`` rather than FastAPI's ``model`` shorthand: the
    shorthand registers the schema under ``application/json``, which would tell the
    generated client that errors arrive as JSON while the server sends
    ``application/problem+json``. A client branching on the media type would treat every
    error as an unrecognised response -- which is exactly the bug the 413 and 429 paths
    had.
    """
    return {
        "description": description,
        "content": {PROBLEM_MEDIA_TYPE: {"schema": {"$ref": "#/components/schemas/ProblemDetail"}}},
        **extra,
    }


ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    400: _documented("The request could not be understood."),
    401: _documented("Credentials are missing (`auth_required`) or refused (`auth_invalid`)."),
    403: _documented(
        "Refused. `permission_denied` means the role may not do this; "
        "`named_human_required` means an agent may not, and a person must."
    ),
    404: _documented("No such record."),
    409: _documented("The record is not in a state that allows this."),
    413: _documented("Request body exceeded the configured ceiling."),
    422: _documented(
        "The body failed schema validation, or a domain rule required a value it did not "
        "get. `detail` is the per-field error list for a schema violation."
    ),
    429: _documented(
        "Rate limited. `Retry-After` carries the interval in seconds.",
        headers={"Retry-After": {"schema": {"type": "integer"}}},
    ),
    503: _documented("A dependency the request needs is not running."),
}
"""Declared on every router so the generated client knows the error shape.

Without a declared response, `openapi-typescript` has no idea a `code` field exists and
every call site casts the error to a hand-written shape. Declaring `ProblemDetail` here is
what makes `web/src/api/schema.d.ts` carry the contract, including the `ProblemCode`
union the UI can switch on.
"""
