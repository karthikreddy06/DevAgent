"""Background job for repository discovery, AST extraction, and embedding."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import get_session_factory
from app.llm.factory import build_embedding_provider
from app.retrieval.indexing import RepoIndexer
from app.services.repo_service import RepoService

logger = get_logger(__name__)


async def index_repository_job(ctx: dict[str, Any], repository_id: str) -> int:
    """Arq background job executing full repository indexing."""
    settings = get_settings()
    session_factory = get_session_factory()
    repo_uuid = uuid.UUID(repository_id)

    async with session_factory() as session:
        repo_service = RepoService(session, settings)
        repo = await repo_service.get_repository(repo_uuid)
        workspace = repo_service.workspace_path(repo.id)

        try:
            embedder = build_embedding_provider(settings)
        except Exception:
            embedder = None

        indexer = RepoIndexer(session=session, embedding_provider=embedder, settings=settings)
        chunks_indexed = await indexer.index_repository(repo, workspace)
        logger.info("index_repo_job_completed", repo_id=repository_id, chunks=chunks_indexed)
        return chunks_indexed
