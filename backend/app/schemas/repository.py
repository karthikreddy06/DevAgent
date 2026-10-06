"""Repository request and response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import AnalysisStatus, CloneStatus, IndexStatus, RepositorySourceType, SymbolKind


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner: str | None = None
    full_name: str | None = None
    source_type: RepositorySourceType = RepositorySourceType.GIT_URL
    source_url: str | None = None
    local_path: str | None = None
    default_branch: str = "main"


class RepositoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    full_name: str
    owner_id: uuid.UUID
    source_type: RepositorySourceType
    source_url: str | None = None
    local_path: str | None = None
    default_branch: str | None = None
    head_sha: str | None = None
    clone_status: CloneStatus
    clone_error: str | None = None
    index_status: IndexStatus
    index_error: str | None = None
    analysis_status: AnalysisStatus
    analysis_error: str | None = None
    indexed_files: int = 0
    indexed_chunks: int = 0
    size_kb: int = 0
    indexed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def owner(self) -> str:
        if "/" in self.full_name:
            return self.full_name.split("/", 1)[0]
        return ""


class SymbolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    signature: str | None = None
    docstring: str | None = None


class RepoFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    path: str
    file_type: str
    size_bytes: int
    line_count: int
    is_test: bool
    ast_parsed: bool
    symbols: list[SymbolRead] = Field(default_factory=list)


class FileContentRead(BaseModel):
    path: str
    content: str
    line_count: int
    size_bytes: int


class FileTreeItem(BaseModel):
    name: str
    path: str
    is_dir: bool
    size_bytes: int = 0
    children: list[FileTreeItem] | None = None
