"""Repository file discovery, AST symbol extraction, and chunk embedding pipeline."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.errors import RepositoryIngestionError
from app.core.ignore import ALWAYS_IGNORED_SUFFIXES, load_ignore_matcher
from app.core.logging import get_logger
from app.llm.base import EmbeddingProvider
from app.models.chunk import CodeChunk
from app.models.code import RepoFile, Symbol
from app.models.enums import CloneStatus, IndexStatus, RepositorySourceType
from app.models.repository import Repository
from app.retrieval.chunking import chunk_file_content

logger = get_logger(__name__)


def compute_sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class RepoIndexer:
    """Indexes a repository's source tree into RepoFile, Symbol, and CodeChunk records."""

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        if embedding_provider is None:
            try:
                from app.llm.factory import build_embedding_provider

                embedding_provider = build_embedding_provider(self.settings)
            except Exception:
                embedding_provider = None
        self.embedder = embedding_provider

    async def index_repository(self, repository: Repository, workspace: Path) -> int:
        """Scan workspace, extract symbols, create chunks with embeddings, and persist."""
        # 1. Pre-indexing validations
        if repository.source_type == RepositorySourceType.GIT_URL and repository.clone_status != CloneStatus.READY:
            repository.index_status = IndexStatus.FAILED
            repository.index_error = (
                f"Cannot index repository: clone status is {repository.clone_status.value} (expected ready)"
            )
            repository.indexed_files = 0
            repository.indexed_chunks = 0
            await self.session.commit()
            logger.error("indexing_precondition_failed", repo_id=str(repository.id), error=repository.index_error)
            raise RepositoryIngestionError(repository.index_error)

        if not workspace.exists():  # noqa: ASYNC240
            repository.index_status = IndexStatus.FAILED
            repository.index_error = f"Cannot index repository: workspace directory does not exist at {workspace}"
            repository.indexed_files = 0
            repository.indexed_chunks = 0
            await self.session.commit()
            logger.error("indexing_precondition_failed", repo_id=str(repository.id), error=repository.index_error)
            raise RepositoryIngestionError(repository.index_error)

        if not workspace.is_dir():  # noqa: ASYNC240
            repository.index_status = IndexStatus.FAILED
            repository.index_error = f"Cannot index repository: workspace path is not a directory at {workspace}"
            repository.indexed_files = 0
            repository.indexed_chunks = 0
            await self.session.commit()
            logger.error("indexing_precondition_failed", repo_id=str(repository.id), error=repository.index_error)
            raise RepositoryIngestionError(repository.index_error)

        repository.index_status = IndexStatus.INDEXING
        repository.index_error = None
        await self.session.commit()

        logger.info("indexing_started", repo_id=str(repository.id), workspace=str(workspace))
        matcher = load_ignore_matcher(workspace)

        try:
            # Clear existing index rows for this repository
            await self.session.execute(delete(CodeChunk).where(CodeChunk.repository_id == repository.id))
            await self.session.execute(delete(Symbol).where(Symbol.repository_id == repository.id))
            await self.session.execute(delete(RepoFile).where(RepoFile.repository_id == repository.id))

            total_files = 0
            total_bytes = 0
            all_chunks: list[CodeChunk] = []

            for item in sorted(workspace.rglob("*")):  # noqa: ASYNC240
                if not item.is_file():
                    continue
                relative = item.relative_to(workspace).as_posix()
                if matcher.is_ignored(relative, is_dir=False):
                    continue
                if item.suffix.lower() in ALWAYS_IGNORED_SUFFIXES:
                    continue

                size = item.stat().st_size
                if size > self.settings.index_max_file_bytes:
                    continue

                try:
                    content = item.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                if "\x00" in content:
                    # Skip binary files that contain NUL bytes (cannot be inserted into PostgreSQL text)
                    continue

                total_files += 1
                total_bytes += size
                content_sha = compute_sha256(content)
                lines = content.splitlines()
                line_count = len(lines)
                is_test = "test" in relative.lower()

                repo_file = RepoFile(
                    repository_id=repository.id,
                    path=relative,
                    language=item.suffix.lstrip(".").lower() or "text",
                    size_bytes=size,
                    line_count=line_count,
                    content_sha=content_sha,
                    is_test=is_test,
                    is_documentation=item.suffix.lower() in (".md", ".rst", ".txt"),
                )
                self.session.add(repo_file)
                await self.session.flush()

                parsed_symbols, parsed_chunks = chunk_file_content(relative, content)

                for sym in parsed_symbols:
                    s = Symbol(
                        repository_id=repository.id,
                        file_id=repo_file.id,
                        name=sym.name,
                        kind=sym.kind,
                        start_line=sym.start_line,
                        end_line=sym.end_line,
                        signature=sym.signature,
                        docstring=sym.docstring,
                    )
                    self.session.add(s)

                for p_chunk in parsed_chunks:
                    c_sha = compute_sha256(p_chunk.content)
                    chunk = CodeChunk(
                        repository_id=repository.id,
                        file_id=repo_file.id,
                        path=relative,
                        chunk_type=p_chunk.chunk_type,
                        symbol_name=p_chunk.symbol_name,
                        language=repo_file.language,
                        start_line=p_chunk.start_line,
                        end_line=p_chunk.end_line,
                        token_count=len(p_chunk.content) // 4,
                        char_count=len(p_chunk.content),
                        content=p_chunk.content,
                        content_sha=c_sha,
                        is_test=is_test,
                        embed_model=self.embedder.model if self.embedder else None,
                    )
                    self.session.add(chunk)
                    all_chunks.append(chunk)

                if total_files >= self.settings.index_max_files:
                    logger.warning("index_max_files_reached", limit=self.settings.index_max_files)
                    break

            await self.session.flush()

            # Enforce non-zero files invariant
            if total_files == 0:
                repository.index_status = IndexStatus.FAILED
                repository.index_error = "Repository workspace contains zero indexable source files"
                repository.indexed_files = 0
                repository.indexed_chunks = 0
                await self.session.commit()
                logger.error("indexing_failed_zero_files", repo_id=str(repository.id))
                raise RepositoryIngestionError(repository.index_error)

            # Enforce non-zero chunks invariant
            if len(all_chunks) == 0:
                repository.index_status = IndexStatus.FAILED
                repository.index_error = f"Repository contains {total_files} file(s) but generated 0 indexable chunks"
                repository.indexed_files = 0
                repository.indexed_chunks = 0
                await self.session.commit()
                logger.error("indexing_failed_zero_chunks", repo_id=str(repository.id), files=total_files)
                raise RepositoryIngestionError(repository.index_error)

            # Compute embeddings in batches if embedder is configured
            if self.embedder and all_chunks:
                batch_size = getattr(self.embedder, "batch_size", 64)
                for i in range(0, len(all_chunks), batch_size):
                    batch = all_chunks[i : i + batch_size]
                    texts = [c.content for c in batch]
                    try:
                        result = await self.embedder.embed(texts)
                        for chunk, vector in zip(batch, result.vectors, strict=False):
                            chunk.embedding = vector
                    except Exception as exc:
                        logger.warning("batch_embedding_failed", error=str(exc))

            repository.indexed_files = total_files
            repository.indexed_chunks = len(all_chunks)
            repository.size_kb = total_bytes // 1024
            repository.index_status = IndexStatus.INDEXED
            repository.index_error = None
            repository.indexed_at = datetime.now(UTC)
            await self.session.commit()

            logger.info(
                "indexing_completed",
                repo_id=str(repository.id),
                files=total_files,
                chunks=len(all_chunks),
                bytes=total_bytes,
            )
            return len(all_chunks)
        except Exception as exc:
            repository.index_status = IndexStatus.FAILED
            if not repository.index_error:
                repository.index_error = f"Indexing failed: {exc}"
            repository.indexed_files = 0
            repository.indexed_chunks = 0
            await self.session.commit()
            if isinstance(exc, RepositoryIngestionError):
                raise
            raise RepositoryIngestionError(repository.index_error) from exc
