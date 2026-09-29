"""Sandbox execution records.

Every container execution is recorded here so the UI and the audit trail can
show exactly what ran, with which limits, for how long, and with which exit
code. Repository code never runs outside these records.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import AgentName, RunStatus

if TYPE_CHECKING:
    from app.models.task import Task


class SandboxRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One ``docker exec`` inside an ephemeral, hardened container."""

    __tablename__ = "sandbox_runs"

    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent: Mapped[AgentName] = mapped_column(enum_column(AgentName, "sandbox_run_agent"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False, default="command")

    image: Mapped[str] = mapped_column(String(200), nullable=False)
    image_digest: Mapped[str | None] = mapped_column(String(120), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    command: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    cwd: Mapped[str] = mapped_column(String(500), nullable=False, default="/workspace")

    # Isolation parameters actually applied (they must match the documented policy).
    network_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cpu_limit: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    mem_limit_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=1024)
    pids_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=256)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    read_only_rootfs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    run_as_user: Mapped[str] = mapped_column(String(40), nullable=False, default="1000:1000")
    capabilities_dropped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "sandbox_run_status"), nullable=False, default=RunStatus.RUNNING
    )
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    oom_killed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    stdout_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stderr_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    stdout_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr_preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cleanup_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[Task] = relationship(back_populates="sandbox_runs")

    def __repr__(self) -> str:
        return f"<SandboxRun {self.command[:2]} exit={self.exit_code} timed_out={self.timed_out}>"
