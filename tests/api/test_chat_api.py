"""Ask HR API: routed answers, SSE streaming, conversation history."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyAnswer, PolicyResult
from hr_agents.config import ApiPrincipalSettings, Settings
from hr_agents.main import create_app
from hr_agents.rbac import RoleId
from hr_agents.services.chat import ChatService
from hr_agents.services.front_door import FrontDoor
from hr_agents.services.workspace_requests import HandoffService
from hr_agents.tools import ToolRegistry
from hr_agents.workspaces import default_registry


class FixedResponder:
    async def ask(self, question: str, *, deps: AgentDeps) -> PolicyResult:
        return PolicyResult(
            answer=PolicyAnswer(
                answer=f"Grounded answer for: {question}",
                citations=["policy.md#1"],
                confidence=0.9,
            )
        )


def _install_fixed_chat(app: FastAPI) -> None:
    audit = app.state.audit
    app.state.chat = ChatService(
        front_door=FrontDoor(),
        responder=FixedResponder(),
        audit=audit,
        tools=ToolRegistry(audit=audit),
    )


def _install_handoffs(app: FastAPI) -> None:
    app.state.handoffs = HandoffService(registry=default_registry(), audit=app.state.audit)


def test_ask_hr_routes_and_answers() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        response = client.post("/v1/chat", json={"message": "berapa saldo cuti saya?"})

        assert response.status_code == 200
        body = response.json()
        assert body["workspace"] == "leave"
        assert body["route_reason"] == "keyword"
        assert body["escalate"] is False
        assert body["citations"] == ["policy.md#1"]
        assert body["conversation_id"]


def test_conversation_history_endpoint() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        first = client.post("/v1/chat", json={"message": "kapan gaji dibayar?"}).json()
        second = client.post(
            "/v1/chat",
            json={
                "message": "dan THR?",
                "conversation_id": first["conversation_id"],
            },
        ).json()
        assert second["conversation_id"] == first["conversation_id"]

        history = client.get(f"/v1/chat/conversations/{first['conversation_id']}")
        assert history.status_code == 200
        turns = history.json()["turns"]
        assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]
        assert history.json()["workspace"] == "payroll"


def _two_employee_app() -> FastAPI:
    """An app where two people are distinct principals, neither an admin.

    The default test install resolves every unauthenticated caller to
    ``local-dev`` with ``hr_admin``, which would pass an ownership check for the
    wrong reason. These guards are about one employee not reading another's
    thread, so the identities have to be real and the roles have to be weak.
    """
    settings = Settings.model_construct(
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("sari-key"), role=RoleId.EMPLOYEE, actor_id="Sari"),
            ApiPrincipalSettings(key=SecretStr("budi-key"), role=RoleId.EMPLOYEE, actor_id="Budi"),
        ],
        api_keys=[],
    )
    return create_app(settings)


def test_a_conversation_is_not_readable_by_another_employee() -> None:
    """An HR chat thread is one employee's private history.

    The conversation record had no owner, so the id was the only thing guarding
    it. ``GET /v1/chat/conversations/{id}`` needed only ``chat:use`` -- the sole
    permission the ``employee`` role has -- so any authenticated employee who
    learned or guessed a UUID could read a colleague's thread. Those threads
    carry payroll and health questions in the plaintext of the conversation.
    """
    app = _two_employee_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        sari = {"X-API-Key": "sari-key"}
        budi = {"X-API-Key": "budi-key"}

        opened = client.post(
            "/v1/chat", json={"message": "kapan gaji saya dibayar?"}, headers=sari
        ).json()
        conversation_id = opened["conversation_id"]

        assert (
            client.get(f"/v1/chat/conversations/{conversation_id}", headers=sari).status_code == 200
        )

        stolen = client.get(f"/v1/chat/conversations/{conversation_id}", headers=budi)

        # 404, not 403: a 403 would confirm the id exists and let a caller
        # enumerate the workspace's conversations.
        assert stolen.status_code == 404
        assert "turns" not in stolen.json().get("detail", {})


def test_a_conversation_cannot_be_continued_by_another_employee() -> None:
    app = _two_employee_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        opened = client.post(
            "/v1/chat", json={"message": "hai"}, headers={"X-API-Key": "sari-key"}
        ).json()

        hijacked = client.post(
            "/v1/chat",
            json={
                "message": "dan gaji bulan ini sudah?",
                "conversation_id": opened["conversation_id"],
            },
            headers={"X-API-Key": "budi-key"},
        )

        assert hijacked.status_code == 404


def test_an_hr_admin_may_read_any_conversation() -> None:
    settings = Settings.model_construct(
        api_principals=[
            ApiPrincipalSettings(key=SecretStr("sari-key"), role=RoleId.EMPLOYEE, actor_id="Sari"),
            ApiPrincipalSettings(key=SecretStr("admin-key"), role=RoleId.HR_ADMIN, actor_id="Rina"),
        ],
        api_keys=[],
    )
    app = create_app(settings)
    with TestClient(app) as client:
        _install_fixed_chat(app)
        opened = client.post(
            "/v1/chat", json={"message": "hai"}, headers={"X-API-Key": "sari-key"}
        ).json()

        read = client.get(
            f"/v1/chat/conversations/{opened['conversation_id']}",
            headers={"X-API-Key": "admin-key"},
        )

    assert read.status_code == 200
    assert [turn["role"] for turn in read.json()["turns"]] == ["user", "assistant"]


def test_unknown_conversation_returns_404() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        response = client.post(
            "/v1/chat",
            json={
                "message": "hai",
                "conversation_id": "00000000-0000-0000-0000-000000000001",
            },
        )
        assert response.status_code == 404


def test_sse_stream_emits_reply_event() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        with client.stream(
            "GET",
            "/v1/chat/stream",
            params={"message": "How do I apply for leave?"},
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            payload = "".join(response.iter_text())

        assert "event: reply" in payload
        assert "Grounded answer" in payload
        assert '"workspace": "leave"' in payload


def test_chat_unavailable_returns_503() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.chat = None
        response = client.post("/v1/chat", json={"message": "hai"})
        assert response.status_code == 503


def test_conversation_cannot_cross_workspaces() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        first = client.post("/v1/chat", json={"message": "berapa saldo cuti saya?"}).json()
        response = client.post(
            "/v1/chat",
            json={"message": "kapan gaji dibayar?", "conversation_id": first["conversation_id"]},
        )
        assert response.status_code == 409


def test_handoff_is_queued_and_listed() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_fixed_chat(app)
        _install_handoffs(app)

        created = client.post(
            "/v1/chat/handoffs",
            json={
                "message": "Onboard Budi, start Monday",
                "source_workspace": "policy",
                "target_workspace": "onboarding",
            },
        )
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "open"
        assert body["target_workspace"] == "onboarding"
        assert body["requested_by"] == "local-dev"

        listed = client.get("/v1/chat/handoffs", params={"workspace": "onboarding"})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [body["id"]]

        every = client.get("/v1/chat/handoffs")
        assert [item["id"] for item in every.json()] == [body["id"]]

        empty = client.get("/v1/chat/handoffs", params={"workspace": "payroll"})
        assert empty.json() == []


def test_self_target_handoff_returns_422() -> None:
    app = create_app()
    with TestClient(app) as client:
        _install_handoffs(app)
        response = client.post(
            "/v1/chat/handoffs",
            json={
                "message": "halo",
                "source_workspace": "policy",
                "target_workspace": "policy",
            },
        )
        assert response.status_code == 422


def test_handoffs_unavailable_returns_503() -> None:
    app = create_app()
    with TestClient(app) as client:
        app.state.handoffs = None
        response = client.post(
            "/v1/chat/handoffs",
            json={
                "message": "halo",
                "source_workspace": "policy",
                "target_workspace": "onboarding",
            },
        )
        assert response.status_code == 503


def test_chat_is_available_after_startup() -> None:
    app = create_app()
    with TestClient(app):
        assert app.state.chat is not None
        assert app.state.handoffs is not None
