"""Proposed change, per-file diff and human approval models.

These tables are the reason DevAgent cannot modify code silently: a change is
persisted as a proposal with a generated diff, and an ``Approval`` row must
exist before any write is performed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import ApprovalDecision, ApprovalKind, ChangeStatus, ChangeType

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class ProposedChange(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A proposed fix: what will change, why, and the unified diff itself."""

    __tablename__ = "proposed_changes"
    __table_args__ = (UniqueConstraint("task_id", "iteration", name="uq_proposed_changes_task_id_iteration"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[ChangeStatus] = mapped_column(
        enum_column(ChangeStatus, "proposed_change_status"), nullable=False, default=ChangeStatus.DRAFT, index=True
    )

    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    files_changed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    patch_unified: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tests_to_run: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    root_cause: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("proposed_changes.id", ondelete="SET NULL"), nullable=True
    )

    task: Mapped[Task] = relationship(back_populates="changes")
    files: Mapped[list[ChangeFile]] = relationship(
        back_populates="change", cascade="all, delete-orphan", passive_deletes=True
    )
    approvals: Mapped[list[Approval]] = relationship(back_populates="change")

    def __repr__(self) -> str:
        return f"<ProposedChange iter={self.iteration} status={self.status} files={self.files_changed}>"


class ChangeFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One file inside a proposal, with the exact before/after content."""

    __tablename__ = "change_files"

    proposed_change_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("proposed_changes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    old_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    change_type: Mapped[ChangeType] = mapped_column(
        enum_column(ChangeType, "change_file_type"), nullable=False, default=ChangeType.MODIFY
    )
    lines_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lines_removed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diff: Mapped[str] = mapped_column(Text, nullable=False, default="")
    original_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposed_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    change: Mapped[ProposedChange] = relationship(back_populates="files")
    task: Mapped[Task] = relationship(back_populates="change_files")

    def __repr__(self) -> str:
        return f"<ChangeFile {self.path} +{self.lines_added}/-{self.lines_removed}>"


class Approval(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A human decision. No write, push or pull request happens without one."""

    __tablename__ = "approvals"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposed_change_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("proposed_changes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[ApprovalKind] = mapped_column(
        enum_column(ApprovalKind, "approval_kind"), nullable=False, default=ApprovalKind.APPLY_CHANGES
    )
    decision: Mapped[ApprovalDecision | None] = mapped_column(
        enum_column(ApprovalDecision, "approval_decision"), nullable=True
    )
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    task: Mapped[Task] = relationship(back_populates="approvals")
    change: Mapped[ProposedChange | None] = relationship(back_populates="approvals")
    decided_by: Mapped[User | None] = relationship()

    @property
    def is_pending(self) -> bool:
        return self.decision is None

    @property
    def is_approved(self) -> bool:
        return self.decision is ApprovalDecision.APPROVED

    def __repr__(self) -> str:
        return f"<Approval {self.kind} decision={self.decision}>"
