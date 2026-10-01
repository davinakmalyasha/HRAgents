"""Authentication middleware: one resolution per request, correct failure codes.

These are the guarantees the old per-endpoint closures could not give. A
regression here is a security regression, not a refactor artefact.
"""

from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.api.auth import AuthenticationMiddleware, current_actor, require_permission
from hr_agents.api.hardening import RateLimiter, client_key, install_hardening
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.rbac import Permission, RoleId

PRINCIPALS = [
    ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="Rina"),
    ApiPrincipalSettings(key=SecretStr("mgr-key"), role=RoleId.MANAGER, actor_id="Budi"),
]


def make_app(settings: Settings, **hardening: Any) -> FastAPI:
    app = FastAPI()

    @app.get("/open")
    async def open_route() -> dict[str, str]:
        return {"ok": "yes"}

    @app.get("/admin-only")
    async def admin_only(request: Request) -> dict[str, str]:
        from hr_agents.api.auth import require_permission

        principal = await require_permission(Permission.PAYROLL_READ)(request)
        return {"actor": principal.actor_id}

    @app.get("/who")
    async def who(request: Request) -> dict[str, Any]:
        return {"actor": current_actor(request).actor_id, "bucket": client_key(request)}

    @app.get("/bucket")
    async def bucket(request: Request) -> dict[str, str]:
        return {"bucket": client_key(request)}

    install_hardening(app, settings, **hardening)
    return app


def test_open_endpoint_answers_without_credentials() -> None:
    """/healthz, /metrics and the SPA must not require a key to answer."""
    with TestClient(make_app(Settings.model_construct(api_principals=PRINCIPALS))) as client:
        assert client.get("/open").status_code == 200


def test_bad_key_is_401_and_missing_key_is_401() -> None:
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        assert client.get("/admin-only", headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.get("/admin-only").status_code == 401


def test_401_and_403_are_distinguishable() -> None:
    """A bad key is 401; a valid key with the wrong role is 403.

    Conflating them tells a client to fix credentials when the real problem is
    the role they hold.
    """
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        unauthorised = client.get("/admin-only", headers={"X-API-Key": "mgr-key"})
        assert unauthorised.status_code == 403
        assert "lacks permission" in unauthorised.json()["detail"]

        authorised = client.get("/admin-only", headers={"X-API-Key": "admin-key"})
        assert authorised.status_code == 200
        assert authorised.json() == {"actor": "Rina"}


def test_actor_comes_from_the_key_not_the_path() -> None:
    """The actor a service records can only be the authenticated one."""
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        body = client.get("/who", headers={"X-API-Key": "mgr-key"}).json()
    assert body["actor"] == "Budi"


def test_rate_limit_buckets_per_principal() -> None:
    """`client_key`'s actor branch was dead code before this middleware existed.

    Two operators behind one NAT now get independent buckets instead of sharing
    one and locking each other out.
    """
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        admin = client.get("/who", headers={"X-API-Key": "admin-key"}).json()["bucket"]
        manager = client.get("/who", headers={"X-API-Key": "mgr-key"}).json()["bucket"]
        assert admin == "actor:Rina"
        assert manager == "actor:Budi"
        assert admin != manager


def test_unauthenticated_requests_fall_back_to_the_key_bucket() -> None:
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        first = client.get("/bucket", headers={"X-API-Key": "admin-key"}).json()["bucket"]
        second = client.get("/bucket", headers={"X-API-Key": "bad"}).json()["bucket"]
    assert first == "actor:Rina"
    assert second != first


def test_bucket_does_not_follow_the_api_key_header() -> None:
    """Varying the presented key must not mint a fresh allowance.

    The unauthenticated fallback used to key on the ``X-API-Key`` header. That
    header is entirely caller-controlled, so rotating it gave every request its
    own bucket and the limiter stopped limiting anything -- a flood, one
    invented key at a time. The fallback is now the peer address.
    """
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        buckets = {
            client.get("/bucket", headers={"X-API-Key": f"guess-{index}"}).json()["bucket"]
            for index in range(5)
        }

    assert len(buckets) == 1, "the bucket key is still attacker-controlled"
    assert next(iter(buckets)).startswith("ip:")


def test_key_is_resolved_once_per_request() -> None:
    """Two guards on one request must not scan the configured keys twice.

    Router-level and endpoint-level permission checks are separate closures;
    without the middleware both would re-resolve the key.
    """

    class CountingPrincipals(list[ApiPrincipalSettings]):
        def __init__(self, *args: Any) -> None:
            super().__init__(*args)
            self.scans = 0

        def __iter__(self) -> Any:
            self.scans += 1
            return super().__iter__()

    principals = CountingPrincipals(PRINCIPALS)
    settings = Settings.model_construct(api_principals=principals)
    app = FastAPI()

    @app.get("/double")
    async def double(request: Request) -> dict[str, str]:
        await require_permission(Permission.PAYROLL_READ)(request)
        await require_permission(Permission.PAYROLL_READ)(request)
        return {"ok": "yes"}

    app.add_middleware(AuthenticationMiddleware, settings=settings)
    with TestClient(app) as client:
        response = client.get("/double", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 200
    assert principals.scans == 1


def test_middleware_never_raises_for_a_bad_key() -> None:
    """A refused key is a value, not an exception: it runs before routing."""
    app = make_app(Settings.model_construct(api_principals=PRINCIPALS))
    with TestClient(app) as client:
        assert client.get("/open", headers={"X-API-Key": "bad"}).status_code == 200


def test_rate_limit_still_applies_per_principal() -> None:
    settings = Settings.model_construct(api_principals=PRINCIPALS)
    app = make_app(settings, limiter=RateLimiter(limit=2))
    with TestClient(app) as client:
        codes = [
            client.get("/open", headers={"X-API-Key": "admin-key"}).status_code for _ in range(4)
        ]
    assert codes[:2] == [200, 200]
    assert codes[2] == 429


def test_actor_name_reaches_the_chain_for_an_unconfigured_install() -> None:
    settings = Settings.model_construct(api_principals=[], api_keys=[], actor_name="Rina")
    app = make_app(settings)
    with TestClient(app) as client:
        assert client.get("/who").json()["actor"] == "Rina"


@pytest.mark.parametrize("role", [RoleId.HR_ADMIN, RoleId.MANAGER, RoleId.FINANCE])
def test_authenticated_actors_are_humans_with_their_role(role: RoleId) -> None:
    settings = Settings.model_construct(
        api_principals=[ApiPrincipalSettings(key=SecretStr("k"), role=role, actor_id="Person")]
    )
    app = FastAPI()

    @app.get("/actor")
    async def actor(request: Request) -> dict[str, Any]:
        ref = current_actor(request)
        audit = ref.audit_actor()
        return {
            "actor_id": audit.actor_id,
            "provenance": audit.provenance.value,
            "role": audit.role,
        }

    app.add_middleware(AuthenticationMiddleware, settings=settings)
    with TestClient(app) as client:
        body = client.get("/actor", headers={"X-API-Key": "k"}).json()
    assert body == {
        "actor_id": "Person",
        "provenance": "authenticated",
        "role": role.value,
    }
