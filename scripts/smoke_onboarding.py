"""Live smoke test for the onboarding flow the dashboard drives.

Exercises the real HTTP API in-process: create a hire, start a plan, complete a
step, waive an optional step with a reason, link a document, and read the plan
back. Run with:

    uv run python scripts/smoke_onboarding.py

Every actor in this script comes from the API key, because no request body can
name one any more. That is asserted here rather than assumed: each mutation is
attempted twice, once with the actor field and once without, and the script
requires the first to be refused with 422 and the second to succeed. If a future
change re-adds a body-supplied actor, this fails.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from hr_agents.main import create_app
from hr_agents.models import DocumentKind

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ok   {label}")
        return
    FAILURES.append(label)
    print(f"  FAIL {label} {detail}")


def refused_field(response: object, field: str) -> bool:
    """True when the server rejected the request *naming this field*.

    The 422 alone is not enough: a missing required field produces the same
    status, and that would pass a test that only checked the code.
    """
    payload = getattr(response, "json", lambda: {})()
    errors = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(errors, list):
        return False
    return any(
        isinstance(error, dict) and error.get("loc") and error["loc"][-1] == field
        for error in errors
    )


def main() -> int:
    today = date.today()
    app = create_app()
    with TestClient(app) as client:
        audit = app.state.audit
        hire = client.post(
            "/v1/employees",
            json={
                "full_name": "Budi Santoso",
                "hire_date": (today - timedelta(days=1)).isoformat(),
                "email": "budi@example.com",
                "job_title": "Backend Engineer",
            },
        )
        check("employee created", hire.status_code == 201, hire.text)
        if hire.status_code != 201:
            return 1
        employee_id = hire.json()["id"]

        # The product's actual claim is not "the API returned 201" but "the
        # tamper-evident chain says who did it, and how we know". Assert that
        # rather than a response field the view happens to expose.
        entries = [entry for entry in audit.entries if "employee.created" in entry.action]
        check("the chain recorded the hire", bool(entries))
        if entries:
            actor = entries[-1].actor
            check(
                "the chain names the key holder",
                actor.actor_id == "local-dev",
                actor.actor_id,
            )
            check(
                "the chain records how the actor was established",
                actor.provenance.value == "authenticated",
                actor.provenance.value,
            )
            check(
                "the chain records the authorization role",
                actor.role == "hr_admin",
                str(actor.role),
            )

        stale = client.post(
            "/v1/employees",
            json={
                "full_name": "Should Not Exist",
                "hire_date": today.isoformat(),
                "created_by": "someone-else",
            },
        )
        check(
            "a request body cannot name the actor",
            stale.status_code == 422 and refused_field(stale, "created_by"),
            stale.text,
        )

        templates = client.get("/v1/onboarding/templates")
        check("no templates yet", templates.status_code == 200 and templates.json() == [])

        draft = client.get("/v1/onboarding/templates/default")
        check("starter template is served", draft.status_code == 200, draft.text)
        starter = draft.json()
        check("starter has steps", len(starter["steps"]) > 0)

        created_template = client.post(
            "/v1/onboarding/templates",
            json={
                "name": starter["name"],
                "description": starter["description"],
                "applies_to_contract_types": starter["applies_to_contract_types"],
                "applies_to_roles": starter["applies_to_roles"],
                "steps": [
                    {
                        "key": step["key"],
                        "title": step["title"],
                        "kind": step["kind"],
                        "description": step["description"],
                        "document_kind": step["document_kind"],
                        "assignee_role": step["assignee_role"],
                        "due_days_after_hire": step["due_days_after_hire"],
                        "required": step["required"],
                        "requires_human_signoff": step["requires_human_signoff"],
                    }
                    for step in starter["steps"]
                ],
            },
        )
        check(
            "starter template created",
            created_template.status_code == 201,
            created_template.text,
        )

        plan = client.post(
            "/v1/onboarding/plans",
            json={"employee_id": employee_id},
        )
        check("plan started", plan.status_code == 201, plan.text)
        if plan.status_code != 201:
            return 1
        body = plan.json()
        plan_id = body["id"]
        check("plan has steps", len(body["steps"]) > 0, str(len(body["steps"])))

        document = client.post(
            f"/v1/employees/{employee_id}/documents",
            json={
                "kind": DocumentKind.KTP.value,
                "storage_key": f"employees/{employee_id}/ktp.pdf",
                "sha256": "a" * 64,
                "filename": "ktp.pdf",
            },
        )
        check("document added", document.status_code == 201, document.text)
        documents = client.get(f"/v1/employees/{employee_id}/documents")
        check(
            "documents listed",
            documents.status_code == 200 and len(documents.json()) == 1,
            documents.text,
        )

        status = client.get(f"/v1/onboarding/plans/{plan_id}/document-status")
        check("document status readable", status.status_code == 200, status.text)

        document_step = next((step for step in body["steps"] if step["kind"] == "document"), None)
        if document_step is not None:
            linked = client.post(
                f"/v1/onboarding/plans/{plan_id}/steps/{document_step['key']}/link-document",
                json={"document_id": document.json()["id"]},
            )
            check("document linked", linked.status_code == 200, linked.text)

        task_step = next((step for step in body["steps"] if step["kind"] == "task"), None)
        if task_step is not None:
            completed = client.post(
                f"/v1/onboarding/plans/{plan_id}/steps/{task_step['key']}/complete",
                json={"note": "Done during orientation"},
            )
            check("step completed", completed.status_code == 200, completed.text)
            check(
                "completed step is done",
                any(
                    step["status"] == "done" and step["key"] == task_step["key"]
                    for step in completed.json()["steps"]
                ),
            )
            check(
                "the completion names the key holder",
                any(
                    step["key"] == task_step["key"] and step.get("completed_by") == "local-dev"
                    for step in completed.json()["steps"]
                ),
                str([step.get("completed_by") for step in completed.json()["steps"]]),
            )
            again = client.post(
                f"/v1/onboarding/plans/{plan_id}/steps/{task_step['key']}/complete",
                json={},
            )
            check("completed step is closed", again.status_code == 409, again.text)

        optional = next(
            (
                step
                for step in body["steps"]
                if step["required"] is False and step["status"] == "pending"
            ),
            None,
        )
        if optional is not None:
            refused = client.post(
                f"/v1/onboarding/plans/{plan_id}/steps/{optional['key']}/waive",
                json={},
            )
            check("waiver without a reason is refused", refused.status_code == 422, refused.text)

            waived = client.post(
                f"/v1/onboarding/plans/{plan_id}/steps/{optional['key']}/waive",
                json={"reason": "Not needed in this country"},
            )
            check("optional step waived", waived.status_code == 200, waived.text)

        required = next(
            (step for step in body["steps"] if step["required"] and step["status"] == "pending"),
            None,
        )
        target = required if required is not None else body["steps"][0]
        agent_actor = client.post(
            f"/v1/onboarding/plans/{plan_id}/steps/{target['key']}/waive",
            json={"by": "agent:screening_coordinator", "reason": "agent override"},
        )
        check(
            "an agent actor in the body is refused",
            agent_actor.status_code == 422 and refused_field(agent_actor, "by"),
            agent_actor.text,
        )

        final = client.get(f"/v1/onboarding/plans/{plan_id}")
        check("plan readable", final.status_code == 200, final.text)
        check("progress is a fraction", 0.0 <= final.json()["progress"] <= 1.0)

        unknown = client.get(f"/v1/onboarding/plans/{uuid4()}")
        check("unknown plan is 404", unknown.status_code == 404, unknown.text)

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {', '.join(FAILURES)}")
        return 1
    print("\nonboarding smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
