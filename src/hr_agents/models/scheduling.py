"""Scheduling domain models — interview slot negotiation and payloads."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from hr_agents.models.common import StrictModel, UtcDateTime
from hr_agents.models.policy import PolicyEvaluation


class SchedulingChannel(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    TELEGRAM = "telegram"
    CALENDAR_INVITE = "calendar_invite"


class TimeSlot(StrictModel):
    """A concrete interview slot in UTC. End must be after start."""

    start_utc: UtcDateTime
    end_utc: UtcDateTime
    tentative: bool = False

    @model_validator(mode="after")
    def _check_order(self) -> TimeSlot:
        if self.end_utc <= self.start_utc:
            raise ValueError("end_utc must be after start_utc")
        return self


class InterviewerAvailability(StrictModel):
    """Free slots for one interviewer; used to detect calendar constraints."""

    interviewer_id: UUID
    display_name: str | None = None
    slots: list[TimeSlot] = Field(default_factory=list)

    @property
    def slot_count(self) -> int:
        return len(self.slots)


class SchedulingPayload(StrictModel):
    """Everything needed to propose or confirm an interview schedule."""

    candidate_id: UUID
    job_id: UUID
    interviewer_ids: list[UUID] = Field(min_length=1)
    slots: list[TimeSlot] = Field(min_length=1)
    timezone: str = Field(default="Asia/Jakarta", description="Candidate IANA timezone")
    channel: SchedulingChannel = SchedulingChannel.EMAIL
    auto_scheduled: bool = False
    policy: PolicyEvaluation
    notes: str | None = Field(default=None, max_length=2000)
