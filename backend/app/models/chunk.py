"""Code chunks (embedded), technology stack findings and dependencies."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import get_settings
from app.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin, enum_column
from app.models.enums import ChunkType, SymbolKind, TechKind

if TYPE_CHECKING:
    from app.models.code import RepoFile
    from app.models.repository import Repository

EMBEDDING_DIM: int = get_settings().embedding_dim


class CodeChunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A retrieval unit: a symbol, a code block, a window, a doc or a config file.

    ``embedding`` is a pgvector column; ``search_vector`` is a database-generated
    tsvector so hybrid (vector + full-text) retrieval needs no external search
    engine (ADR-0005).
    """

    __tablename__ = "code_chunks"
    __table_args__ = (
        UniqueConstraint("file_id", "content_sha", name="uq_code_chunks_file_id_content_sha"),
        Index(
            "ix_code_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_code_chunks_search_vector_gin", "search_vector", postgresql_using="gin"),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repo_files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    chunk_type: Mapped[ChunkType] = mapped_column(
        enum_column(ChunkType, "code_chunk_type"), nullable=False, default=ChunkType.WINDOW
    )
    symbol_name: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    symbol_kind: Mapped[SymbolKind | None] = mapped_column(
        enum_column(SymbolKind, "code_chunk_symbol_kind"), nullable=True
    )
    language: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    start_line: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    search_vector: Mapped[Any | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', content)", persisted=True), nullable=True
    )

    file: Mapped[RepoFile] = relationship(back_populates="chunks")
    repository: Mapped[Repository] = relationship(back_populates="chunks")

    @property
    def line_range(self) -> str:
        return f"{self.start_line}-{self.end_line}"

    def __repr__(self) -> str:
        return f"<CodeChunk {self.path}:{self.start_line}-{self.end_line} type={self.chunk_type}>"


class TechStackFinding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A detected language, framework, package manager, test runner or CI system."""

    __tablename__ = "tech_stack_findings"
    __table_args__ = (UniqueConstraint("repository_id", "kind", "name", name="uq_tech_stack_findings_repo_kind_name"),)

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[TechKind] = mapped_column(enum_column(TechKind, "tech_stack_kind"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str | None] = mapped_column(String(60), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), nullable=False, default="high")
    evidence_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="tech_stack")


class Dependency(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A declared dependency parsed from a manifest file."""

    __tablename__ = "dependencies"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "ecosystem", "name", "manifest_path", name="uq_dependencies_repo_eco_name_manifest"
        ),
    )

    repository_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    ecosystem: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version_spec: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_dev: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    manifest_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    manifest_kind: Mapped[str | None] = mapped_column(String(40), nullable=True)

    repository: Mapped[Repository] = relationship(back_populates="dependencies")
