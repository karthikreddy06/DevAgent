"""Repository creation, exploration, and indexing endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, get_repo_service
from app.models.user import User
from app.retrieval.indexing import RepoIndexer
from app.schemas.common import StatusResponse
from app.schemas.repository import FileContentRead, FileTreeItem, RepositoryCreate, RepositoryRead
from app.services.repo_service import RepoService

router = APIRouter(prefix="/repositories", tags=["repositories"])


@router.post("", response_model=RepositoryRead, status_code=status.HTTP_201_CREATED)
async def create_repository(
    req: RepositoryCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
) -> RepositoryRead:
    repo = await service.create_repository(req, owner=current_user)
    return RepositoryRead.model_validate(repo)


@router.get("", response_model=list[RepositoryRead])
async def list_repositories(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
) -> list[RepositoryRead]:
    repos = await service.list_repositories(owner_id=current_user.id)
    return [RepositoryRead.model_validate(r) for r in repos]


@router.get("/{repo_id}", response_model=RepositoryRead)
async def get_repository(
    repo_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
) -> RepositoryRead:
    repo = await service.get_repository(repo_id)
    return RepositoryRead.model_validate(repo)


@router.get("/{repo_id}/tree", response_model=list[FileTreeItem])
async def get_repository_tree(
    repo_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
) -> list[FileTreeItem]:
    return await service.get_file_tree(repo_id)


@router.get("/{repo_id}/files", response_model=FileContentRead)
async def read_file(
    repo_id: uuid.UUID,
    path: Annotated[str, Query(description="Relative file path in workspace")],
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
) -> FileContentRead:
    return await service.read_file_content(repo_id, path)


@router.post("/{repo_id}/index", response_model=StatusResponse)
async def index_repository(
    repo_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[RepoService, Depends(get_repo_service)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StatusResponse:
    repo = await service.get_repository(repo_id)
    workspace = service.workspace_path(repo.id)
    indexer = RepoIndexer(session=db)
    await indexer.index_repository(repo, workspace)
    return StatusResponse(status="indexed")
