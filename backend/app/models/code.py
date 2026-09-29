"""Indexed repository files and extracted symbols."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import SymbolKind

if TYPE_CHECKING:
    from app.models.chunk import CodeChunk
    from app.models.repository import Repository


class RepoFile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A file that survived discovery filters and was indexed."""

    __tablename__ = "repo_files"
    __table_args__ = (UniqueConstraint("repository_id", "path", name="uq_repo_files_repository_id_path"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_binary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_documentation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Module-level imports, used for cheap dependency context and "who imports X".
    imports: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="files")
    symbols: Mapped[list[Symbol]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )
    chunks: Mapped[list[CodeChunk]] = relationship(
        back_populates="file", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def directory(self) -> str:
        return self.path.rsplit("/", 1)[0] if "/" in self.path else ""

    def __repr__(self) -> str:
        return f"<RepoFile {self.path} lang={self.language}>"


class Symbol(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A function, method or class extracted from a file."""

    __tablename__ = "symbols"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repo_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    kind: Mapped[SymbolKind] = mapped_column(enum_column(SymbolKind, "symbol_kind"), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    docstring: Mapped[str | None] = mapped_column(Text, nullable=True)

    file: Mapped[RepoFile] = relationship(back_populates="symbols")
    repository: Mapped[Repository] = relationship(back_populates="symbols")

    def __repr__(self) -> str:
        return f"<Symbol {self.kind}:{self.name}@{self.start_line}-{self.end_line}>"
