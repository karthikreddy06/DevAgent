"""Task and task event models (the state machine's persistent record)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import EventLevel, TaskStatus, TaskType

if TYPE_CHECKING:
    from app.models.agent import AgentRun, ToolExecution
    from app.models.change import Approval, ChangeFile, ProposedChange
    from app.models.git import GitOperation
    from app.models.repository import Repository
    from app.models.sandbox import SandboxRun
    from app.models.testing import TestRun
    from app.models.user import User


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A unit of work: a bug report, feature request or question about a repo."""

    __tablename__ = "tasks"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[TaskType] = mapped_column(enum_column(TaskType, "task_type"), nullable=False, default=TaskType.BUG)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    base_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[TaskStatus] = mapped_column(
        enum_column(TaskStatus, "task_status"), nullable=False, default=TaskStatus.CREATED, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    job_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Planner output, debugger output, final report, failure detail, budget usage.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    root_cause: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    budget_usage: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    total_prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sandbox_run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    awaiting_approval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="tasks")
    owner: Mapped[User] = relationship(back_populates="tasks")
    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True, order_by="TaskEvent.seq"
    )
    agent_runs: Mapped[list[AgentRun]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    tool_executions: Mapped[list[ToolExecution]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    sandbox_runs: Mapped[list[SandboxRun]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    test_runs: Mapped[list[TestRun]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    changes: Mapped[list[ProposedChange]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True, order_by="ProposedChange.iteration"
    )
    change_files: Mapped[list[ChangeFile]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )
    git_operations: Mapped[list[GitOperation]] = relationship(
        back_populates="task", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED}

    @property
    def is_awaiting_human(self) -> bool:
        return self.status is TaskStatus.AWAITING_APPROVAL

    def __repr__(self) -> str:
        return f"<Task {self.title!r} status={self.status} iteration={self.iteration}>"


class TaskEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An append-only event in a task's timeline (source of the SSE stream)."""

    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_events_task_id_seq"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    level: Mapped[EventLevel] = mapped_column(
        enum_column(EventLevel, "task_event_level"), nullable=False, default=EventLevel.INFO
    )
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    task: Mapped[Task] = relationship(back_populates="events")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        if "event_type" in kwargs and "type" not in kwargs:
            kwargs["type"] = kwargs.pop("event_type")
        super().__init__(*args, **kwargs)

    @property
    def event_type(self) -> str:
        return self.type

    @event_type.setter
    def event_type(self, val: str) -> None:
        self.type = val

    def __repr__(self) -> str:
        return f"<TaskEvent #{self.seq} {self.type}>"
