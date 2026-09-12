"""Ask HR chat endpoints: routed answers and SSE streaming.

The front door routes each message to a workspace pack; answers are grounded by
the Policy Assistant and escalated deterministically when grounding fails. No
chat path executes a consequential action.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from hr_agents.api.chat_schemas import (
    ChatReplyView,
    ChatRequest,
    ConversationView,
    HandoffRequest,
    HandoffView,
)
from hr_agents.api.deps import get_principal, require_permission
from hr_agents.rbac import Permission, Principal
from hr_agents.services.chat import ChatError, ChatService, ChatWorkspaceMismatch
from hr_agents.services.workspace_requests import HandoffError, HandoffService
from hr_agents.workspaces import WorkspaceId

router = APIRouter(
    prefix="/v1/chat",
    tags=["chat"],
    dependencies=[Depends(require_permission(Permission.CHAT_USE))],
)


def get_chat(request: Request) -> ChatService:
    service: ChatService | None = getattr(request.app.state, "chat", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="chat is unavailable: the knowledge base is not loaded",
        )
    return service


ChatDep = Annotated[ChatService, Depends(get_chat)]
PrincipalDep = Annotated[Principal, Depends(get_principal)]


def get_handoffs(request: Request) -> HandoffService:
    service: HandoffService | None = getattr(request.app.state, "handoffs", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="handoffs are unavailable: the knowledge base is not loaded",
        )
    return service


HandoffDep = Annotated[HandoffService, Depends(get_handoffs)]


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@router.post("", response_model=ChatReplyView, summary="Ask HR (routed, grounded answers)")
async def ask_hr(payload: ChatRequest, chat: ChatDep, principal: PrincipalDep) -> ChatReplyView:
    try:
        reply = await chat.ask(
            message=payload.message,
            principal=principal,
            workspace=payload.workspace,
            conversation_id=payload.conversation_id,
        )
    except ChatWorkspaceMismatch as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ChatReplyView.from_model(reply)


@router.post(
    "/handoffs",
    response_model=HandoffView,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a request in another workspace (human-invoked)",
)
def request_handoff(
    payload: HandoffRequest,
    handoffs: HandoffDep,
    principal: PrincipalDep,
) -> HandoffView:
    try:
        record = handoffs.request(
            message=payload.message,
            principal=principal,
            source_workspace=payload.source_workspace,
            target_workspace=payload.target_workspace,
        )
    except HandoffError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    return HandoffView.from_model(record)


@router.get(
    "/handoffs",
    response_model=list[HandoffView],
    summary="Open handoffs, optionally filtered to one workspace",
)
def list_handoffs(
    handoffs: HandoffDep,
    workspace: WorkspaceId | None = None,
) -> list[HandoffView]:
    return [HandoffView.from_model(record) for record in handoffs.open_for(workspace)]


@router.get("/stream", summary="Ask HR over server-sent events")
async def stream_hr(
    message: str,
    chat: ChatDep,
    principal: PrincipalDep,
    workspace: WorkspaceId | None = None,
    conversation_id: UUID | None = None,
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            reply = await chat.ask(
                message=message,
                principal=principal,
                workspace=workspace,
                conversation_id=conversation_id,
            )
        except ChatError as exc:
            yield _sse("error", {"detail": str(exc)})
            return
        yield _sse("reply", reply.model_dump(mode="json"))

    return StreamingResponse(events(), media_type="text/event-stream")


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationView,
    summary="Conversation history",
)
def get_conversation(conversation_id: UUID, chat: ChatDep) -> ConversationView:
    record = chat.get_conversation(conversation_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"unknown conversation {conversation_id}",
        )
    return ConversationView.from_model(record)
