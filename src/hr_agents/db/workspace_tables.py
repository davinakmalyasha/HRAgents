"""SQLAlchemy tables for the two stores that survive a restart.

`chat_conversations` and `workspace_requests` back the Ask HR transcript and the
cross-workspace handoff queue. Both services held their state in a plain dict, so
a container restart or a second replica emptied them: an answer the employee had
already been given could not be shown again, and a handoff vanished mid-workflow.

Named `chat_conversations`, not `conversations` -- `tables.ConversationRecord` is
the candidate-messaging conversation with a `candidate_id` foreign key and an SLA
deadline, and reusing that name for an HR chat thread would have been two different
records behind one table.

Every index here leads with `tenant_id`, which is the first index on that column
anywhere in this schema. Row-level security filters every query by tenant, so
without it the isolation layer is also a sequential scan of the whole table: the
security mechanism sets the performance floor for every tenant-scoped read.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    DateTime,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hr_agents.db.base import Base, TenantScoped

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class ChatConversationRecord(TenantScoped, Base):
    """One Ask HR thread: workspace, owner, and the turns exchanged."""

    __tablename__ = "chat_conversations"
    __table_args__ = (
        # Tenant-leading, because every query is tenant-filtered by RLS.
        Index("ix_chat_conversations_tenant", "tenant_id"),
        # `ChatService.get_conversation` authorises on owner, so the read path is
        # "this owner's threads in this workspace, newest first".
        Index("ix_chat_conversations_tenant_owner", "tenant_id", "owner"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    workspace: Mapped[str] = mapped_column(String(64), nullable=False)
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    turns: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class WorkspaceRequestRecord(TenantScoped, Base):
    """One cross-workspace handoff request -- a queue item, never a decision."""

    __tablename__ = "workspace_requests"
    __table_args__ = (
        Index("ix_workspace_requests_tenant", "tenant_id"),
        # `HandoffService.open_for` filters on target workspace and status, which is
        # what the receiving team's queue view reads.
        Index(
            "ix_workspace_requests_tenant_target_status",
            "tenant_id",
            "target_workspace",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    source_workspace: Mapped[str] = mapped_column(String(64), nullable=False)
    target_workspace: Mapped[str] = mapped_column(String(64), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
