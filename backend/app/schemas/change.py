"""Proposed changes and approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ApprovalDecision, ApprovalKind, ChangeStatus, ChangeType


class ChangeFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    change_id: uuid.UUID
    path: str
    change_type: ChangeType
    old_content: str | None = None
    new_content: str | None = None
    patch: str | None = None
    created_at: datetime


class ProposedChangeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    agent_run_id: uuid.UUID | None = None
    title: str
    summary: str
    unified_diff: str
    status: ChangeStatus
    created_at: datetime
    updated_at: datetime
    files: list[ChangeFileRead] = Field(default_factory=list)


class ApprovalDecisionRequest(BaseModel):
    decision: ApprovalDecision
    notes: str | None = None


class ChangeReviewRequest(BaseModel):
    approved: bool
    reason: str | None = None


class ChangeItemRead(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    patch_unified: str
    files_changed: list[str] = Field(default_factory=list)
    summary: str | None = None
    status: str
    test_status: str = "pending"
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    created_at: datetime


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    change_id: uuid.UUID | None = None
    kind: ApprovalKind
    decision: ApprovalDecision
    requested_by: str
    decided_by: str | None = None
    notes: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
