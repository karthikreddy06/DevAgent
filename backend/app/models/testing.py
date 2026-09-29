"""Test run and individual test case records."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import RunStatus, TestOutcome

if TYPE_CHECKING:
    from app.models.task import Task


class TestRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The result of executing a test suite inside the sandbox."""

    __tablename__ = "test_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sandbox_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("sandbox_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    framework: Mapped[str] = mapped_column(String(60), nullable=False, default="unknown")
    command: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "test_run_status"), nullable=False, default=RunStatus.RUNNING
    )
    # What this run was for: "baseline" (before the fix) or "verification" (after).
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="baseline")
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    all_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    stdout_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stderr_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stdout_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_tail: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship(back_populates="test_runs")
    cases: Mapped[list[TestCase]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def failed_total(self) -> int:
        return self.failed + self.errors

    def __repr__(self) -> str:
        return f"<TestRun {self.framework} {self.passed}/{self.total} passed={self.all_passed}>"


class TestCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single test case outcome, including its failure detail."""

    __tablename__ = "test_cases"

    test_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    suite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[TestOutcome] = mapped_column(enum_column(TestOutcome, "test_case_status"), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)

    test_run: Mapped[TestRun] = relationship(back_populates="cases")

    def __repr__(self) -> str:
        return f"<TestCase {self.name} {self.status}>"
