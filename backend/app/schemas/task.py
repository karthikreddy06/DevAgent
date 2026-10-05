"""Task lifecycle and event schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EventLevel, TaskStatus, TaskType


class TaskCreate(BaseModel):
    repository_id: uuid.UUID
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    type: TaskType = TaskType.BUG_FIX
    base_branch: str | None = None
    target_files: list[str] | None = None
    test_command: str | None = None


class TaskEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    seq: int
    event_type: str
    level: EventLevel
    message: str
    payload: dict[str, Any] | None = None
    created_at: datetime


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    user_id: uuid.UUID
    type: TaskType
    title: str
    description: str
    status: TaskStatus
    base_branch: str | None = None
    iteration: int = 1
    plan: dict[str, Any] | None = None
    root_cause: dict[str, Any] | None = None
    summary: str | None = None
    error: dict[str, Any] | None = None
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    tool_call_count: int = 0
    created_at: datetime
    updated_at: datetime


class TaskCancelRequest(BaseModel):
    reason: str = "User cancelled task"
