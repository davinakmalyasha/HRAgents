"""Offer tables — full offer records with append-only terms revisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hr_agents.db.base import Base, TenantScoped
from hr_agents.db.tables import JSONVariant


class OfferRecord(TenantScoped, Base):
    __tablename__ = "offers"
    __table_args__ = (
        Index("ix_offers_application", "application_id"),
        Index("ix_offers_candidate", "candidate_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    application_id: Mapped[UUID] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    decided_by: Mapped[str | None] = mapped_column(String(200))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    declined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decline_reason: Mapped[str | None] = mapped_column(Text)

    revisions: Mapped[list[OfferRevisionRecord]] = relationship(
        back_populates="offer", order_by="OfferRevisionRecord.revision_index"
    )


class OfferRevisionRecord(TenantScoped, Base):
    __tablename__ = "offer_revisions"
    __table_args__ = (Index("ix_offer_revisions_offer", "offer_id"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    offer_id: Mapped[UUID] = mapped_column(
        ForeignKey("offers.id", ondelete="CASCADE"), nullable=False
    )
    revision_index: Mapped[int] = mapped_column(Integer, nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSONVariant, nullable=False)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    offer: Mapped[OfferRecord] = relationship(back_populates="revisions")
