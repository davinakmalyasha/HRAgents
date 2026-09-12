"""Ask HR API: routed answers, SSE streaming, conversation history."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyAnswer, PolicyResult
from hr_agents.main import create_app
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
