"""`GET /v1/session` — the caller's own identity.

The approvals inbox and the growth queue both need to know the authenticated actor's role
to render honestly. Before this endpoint they guessed, and a guess is how a UI ends up
offering a decision the server refuses.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.models import ApproverRole
from hr_agents.rbac import Principal, RoleId, may_decide_for

PRINCIPALS = [
    ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="Rina"),
    ApiPrincipalSettings(key=SecretStr("mgr-key"), role=RoleId.MANAGER, actor_id="Budi"),
]


def client_for(*principals: ApiPrincipalSettings) -> TestClient:
    """The real app, so the error contract is the one production serves."""
    return TestClient(create_app(Settings.model_construct(api_principals=list(principals))))


def test_reports_the_authenticated_identity() -> None:
    with client_for(*PRINCIPALS) as client:
        response = client.get("/v1/session", headers={"X-API-Key": "mgr-key"})

    assert response.status_code == 200
    body = response.json()
    assert body["actor_id"] == "Budi"
    assert body["role"] == "manager"
    assert body["employee_id"] is None
    assert body["api_key"] is False


def test_publishes_which_approver_roles_the_caller_may_decide() -> None:
    """The server's own `APPROVER_ROLE_HOLDERS`, not a copy the client keeps in step.

    The inbox needs to know this to hide a decision that is not the viewer's. A client
    that copied the table would be one edit away from hiding everything, or offering
    something it has no authority for.
    """
    with client_for(*PRINCIPALS) as client:
        manager = client.get("/v1/session", headers={"X-API-Key": "mgr-key"}).json()
        admin = client.get("/v1/session", headers={"X-API-Key": "admin-key"}).json()

    # A manager may act for `manager`, `engineering_lead` and `recruiter_lead` -- the
    # hiring manager is the engineering lead at an SME -- but not for finance or for
    # `data_protection`, which at this deployment means hr_admin alone.
    assert manager["decides_approver_roles"] == ["engineering_lead", "manager", "recruiter_lead"]
    assert "data_protection" in admin["decides_approver_roles"]
    assert "finance" in admin["decides_approver_roles"]


def test_a_role_with_no_approver_authority_is_told_so() -> None:
    """An empty list is the answer, not a missing field.

    A client defaulting an absent field to "can decide everything" would turn this
    endpoint into the exact hole it exists to close.
    """
    employee = ApiPrincipalSettings(key=SecretStr("emp-key"), role=RoleId.EMPLOYEE, actor_id="Sari")
    with client_for(employee) as client:
        response = client.get("/v1/session", headers={"X-API-Key": "emp-key"})

    assert response.json()["decides_approver_roles"] == []


def test_the_published_authority_matches_the_service_that_enforces_it() -> None:
    """One table, two readers.

    If these ever disagree the inbox hides decisions it could have taken, or offers ones
    it cannot -- so the assertion is against `may_decide_for`, not a literal list.
    """
    with client_for(*PRINCIPALS) as client:
        published = set(
            client.get("/v1/session", headers={"X-API-Key": "mgr-key"}).json()[
                "decides_approver_roles"
            ]
        )

    for approver_role in ApproverRole:
        principal = Principal(actor_id="Budi", role=RoleId.MANAGER)
        if may_decide_for(principal, approver_role.value):
            assert approver_role.value in published
        else:
            assert approver_role.value not in published


def test_role_comes_from_the_credential_not_the_request() -> None:
    """The role is the one every permission check uses.

    A query field naming a role would be a way to ask for authority the credential does
    not carry, so the response is built from the resolved principal alone.
    """
    with client_for(*PRINCIPALS) as client:
        asked_for_admin = client.get("/v1/session?role=hr_admin", headers={"X-API-Key": "mgr-key"})

    assert asked_for_admin.status_code == 200
    assert asked_for_admin.json()["role"] == "manager"


def test_carries_the_employee_binding_when_there_is_one() -> None:
    """A self-service principal is bound to a record, and the client needs that id."""
    employee_id = uuid4()
    principal = ApiPrincipalSettings(
        key=SecretStr("self-key"),
        role=RoleId.EMPLOYEE,
        actor_id="Sari",
        employee_id=employee_id,
    )
    with client_for(principal) as client:
        response = client.get("/v1/session", headers={"X-API-Key": "self-key"})

    assert response.status_code == 200
    assert response.json()["employee_id"] == str(employee_id)


def test_an_unbound_key_says_so_rather_than_implying_an_identity() -> None:
    """`api_key: true` is what stops the dashboard implying a managed identity."""
    settings = Settings.model_construct(api_keys=["shared-secret"])
    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/session", headers={"X-API-Key": "shared-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["api_key"] is True
    assert body["actor_id"] == "api-key"


def test_no_credentials_is_401_not_an_anonymous_session() -> None:
    """An inbox that answered "you are nobody" would render every button disabled with no
    explanation, which is worse than refusing."""
    with client_for(*PRINCIPALS) as client:
        response = client.get("/v1/session")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "auth_required"


def test_a_wrong_key_is_401_and_says_so_distinctly() -> None:
    """`auth_required` and `auth_invalid` are different problems with different fixes."""
    with client_for(*PRINCIPALS) as client:
        response = client.get("/v1/session", headers={"X-API-Key": "nope"})

    assert response.status_code == 401
    assert response.json()["code"] == "auth_invalid"


def test_never_echoes_the_credential() -> None:
    """Nothing in the response may contain the key, even in an error."""
    with client_for(*PRINCIPALS) as client:
        ok = client.get("/v1/session", headers={"X-API-Key": "admin-key"})
        bad = client.get("/v1/session", headers={"X-API-Key": "super-secret-guess"})

    for response in (ok, bad):
        assert "admin-key" not in response.text
        assert "super-secret-guess" not in response.text


def test_declares_the_problem_media_type_on_its_failures() -> None:
    """The 401 is the same contract as every other error in the app."""
    with client_for(*PRINCIPALS) as client:
        response = client.get("/v1/session")

    assert response.json()["type"].endswith("auth_required")
    assert response.json()["status"] == 401
