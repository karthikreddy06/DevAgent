"""Repository and branch models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import (
    AnalysisStatus,
    CloneStatus,
    IndexStatus,
    RepositorySourceType,
)

if TYPE_CHECKING:
    from app.models.chunk import CodeChunk, Dependency, TechStackFinding
    from app.models.code import RepoFile, Symbol
    from app.models.task import Task
    from app.models.user import User


class Repository(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """An imported repository (cloned into the workspace)."""

    __tablename__ = "repositories"
    __table_args__ = (UniqueConstraint("owner_id", "full_name", name="uq_repositories_owner_id_full_name"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    full_name: Mapped[str] = mapped_column(String(400), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="github")
    source_type: Mapped[RepositorySourceType] = mapped_column(
        enum_column(RepositorySourceType, "repository_source_type"), nullable=False
    )
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    default_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    clone_status: Mapped[CloneStatus] = mapped_column(
        enum_column(CloneStatus, "repository_clone_status"), nullable=False, default=CloneStatus.PENDING
    )
    clone_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cloned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    analysis_status: Mapped[AnalysisStatus] = mapped_column(
        enum_column(AnalysisStatus, "repository_analysis_status"), nullable=False, default=AnalysisStatus.NOT_ANALYZED
    )
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # CodebaseMap: languages, frameworks, package managers, entry points, modules.
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    index_status: Mapped[IndexStatus] = mapped_column(
        enum_column(IndexStatus, "repository_index_status"), nullable=False, default=IndexStatus.NOT_INDEXED
    )
    index_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    index_head_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    indexed_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    indexed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embed_model: Mapped[str | None] = mapped_column(String(120), nullable=True)

    owner: Mapped[User] = relationship(back_populates="repositories")
    branches: Mapped[list[RepositoryBranch]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", lazy="selectin"
    )
    files: Mapped[list[RepoFile]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )
    chunks: Mapped[list[CodeChunk]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )
    symbols: Mapped[list[Symbol]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )
    tech_stack: Mapped[list[TechStackFinding]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", lazy="selectin"
    )
    dependencies: Mapped[list[Dependency]] = relationship(
        back_populates="repository", cascade="all, delete-orphan", passive_deletes=True
    )
    tasks: Mapped[list[Task]] = relationship(back_populates="repository", cascade="all, delete-orphan")

    @property
    def is_ready(self) -> bool:
        """True when the clone is usable by the rest of the pipeline."""
        return self.clone_status is CloneStatus.READY

    def display_branch(self) -> str:
        return self.default_branch or "main"

    def __repr__(self) -> str:
        return f"<Repository {self.full_name} clone={self.clone_status} index={self.index_status}>"


class RepositoryBranch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A branch discovered in the cloned repository."""

    __tablename__ = "repository_branches"
    __table_args__ = (UniqueConstraint("repository_id", "name", name="uq_repository_branches_repository_id_name"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    repository: Mapped[Repository] = relationship(back_populates="branches")
