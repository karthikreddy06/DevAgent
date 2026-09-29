"""Git operation records.

The MVP performs no remote git mutations at all (no push, no pull request).
Local, non-destructive operations (status, branch, commit inside the task
workspace) are recorded here so the UI can show what happened, and the schema is
ready for the approval-gated push/PR phase.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import GitOperationKind, GitOperationStatus

if TYPE_CHECKING:
    from app.models.task import Task


class GitOperation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single git command execution and its outcome."""

    __tablename__ = "git_operations"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[GitOperationKind] = mapped_column(enum_column(GitOperationKind, "git_operation_kind"), nullable=False)
    status: Mapped[GitOperationStatus] = mapped_column(
        enum_column(GitOperationStatus, "git_operation_status"), nullable=False, default=GitOperationStatus.PENDING
    )
    branch: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task | None] = relationship(back_populates="git_operations")

    def __repr__(self) -> str:
        return f"<GitOperation {self.kind} status={self.status}>"
