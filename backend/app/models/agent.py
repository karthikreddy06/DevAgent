"""Agent run, agent step and tool execution records (the audit trail)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AgentName, RunStatus, StepKind

if TYPE_CHECKING:
    from app.models.task import Task


class AgentRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One execution of one agent inside one task iteration."""

    __tablename__ = "agent_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent: Mapped[AgentName] = mapped_column(enum_column(AgentName, "agent_name"), nullable=False, index=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "agent_run_status"), nullable=False, default=RunStatus.PENDING
    )
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    budget_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="agent_runs")
    steps: Mapped[list[AgentStep]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentStep.step_index",
    )

    def __repr__(self) -> str:
        return f"<AgentRun {self.agent} status={self.status} iter={self.iteration}>"


class AgentStep(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single step inside an agent run: an LLM call, a tool call or a decision."""

    __tablename__ = "agent_steps"

    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[StepKind] = mapped_column(enum_column(StepKind, "agent_step_kind"), nullable=False)
    tool_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "agent_step_status"), nullable=False, default=RunStatus.SUCCEEDED
    )
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    agent_run: Mapped[AgentRun] = relationship(back_populates="steps")

    def __repr__(self) -> str:
        return f"<AgentStep #{self.step_index} {self.kind} {self.tool_name or ''}>"


class ToolExecution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Every tool invocation, with redacted arguments and captured output refs."""

    __tablename__ = "tool_executions"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    agent: Mapped[AgentName] = mapped_column(enum_column(AgentName, "tool_execution_agent"), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False)
    args: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "tool_execution_status"), nullable=False, default=RunStatus.RUNNING
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stderr_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stdout_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sandbox_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sandbox_runs.id", ondelete="SET NULL"), nullable=True
    )

    task: Mapped[Task] = relationship(back_populates="tool_executions")

    def __repr__(self) -> str:
        return f"<ToolExecution {self.tool_name} status={self.status} exit={self.exit_code}>"
