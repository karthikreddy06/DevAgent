"""Agent runs, steps, and tool execution schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AgentName, RunStatus, StepKind


class ToolExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    step_id: uuid.UUID
    tool_name: str
    permission: str
    arguments: dict[str, Any]
    ok: bool
    output: str
    duration_ms: int
    sandboxed: bool
    sandbox_run_id: uuid.UUID | None = None
    created_at: datetime


class AgentStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_run_id: uuid.UUID
    step_number: int
    kind: StepKind
    prompt: str
    response: str
    rationale: str | None = None
    duration_ms: int
    created_at: datetime
    tool_executions: list[ToolExecutionRead] = Field(default_factory=list)


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    agent_name: AgentName
    status: RunStatus
    step_count: int
    tool_call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    error: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[AgentStepRead] = Field(default_factory=list)
