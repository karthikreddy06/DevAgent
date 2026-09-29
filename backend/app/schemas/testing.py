"""Test execution schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import RunStatus, TestOutcome


class TestCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    test_run_id: uuid.UUID
    name: str
    file_path: str | None = None
    line_number: int | None = None
    outcome: TestOutcome
    duration_ms: int
    failure_message: str | None = None
    error_trace: str | None = None
    created_at: datetime


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    status: RunStatus
    total_count: int
    passed_count: int
    failed_count: int
    error_count: int
    skipped_count: int
    duration_ms: int
    stdout: str
    stderr: str
    created_at: datetime
    test_cases: list[TestCaseRead] = Field(default_factory=list)
