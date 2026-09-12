"""Ask HR API: routed answers, SSE streaming, conversation history."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hr_agents.agents.deps import AgentDeps
from hr_agents.agents.policy_assistant import PolicyAnswer, PolicyResult
from hr_agents.main import create_app
from hr_agents.services.chat import ChatService
from hr_agents.services.front_door import FrontDoor
from hr_agents.tools import ToolRegistry


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


def test_chat_is_available_after_startup() -> None:
    app = create_app()
    with TestClient(app):
        assert app.state.chat is not None
