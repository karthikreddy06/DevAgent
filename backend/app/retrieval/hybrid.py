"""Hybrid vector and full-text search implementation conforming to CodeSearch protocol."""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.llm.base import EmbeddingProvider
from app.models.chunk import CodeChunk
from app.models.code import RepoFile, Symbol
from app.tools.base import CodeHit, CodeSearch

logger = get_logger(__name__)


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    if len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2, strict=False))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class HybridRetriever(CodeSearch):
    """Hybrid code search combining semantic vector search and keyword match."""

    def __init__(
        self,
        repository_id: uuid.UUID,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.repository_id = repository_id
        self.session = session
        self.settings = settings or get_settings()
        if embedding_provider is None:
            try:
                from app.llm.factory import build_embedding_provider

                embedding_provider = build_embedding_provider(self.settings)
            except Exception:
                embedding_provider = None
        self.embedder = embedding_provider

    async def search(self, query: str, *, top_k: int = 8) -> list[CodeHit]:
        """Perform hybrid retrieval over the repository's code chunks."""
        hits: dict[uuid.UUID, CodeHit] = {}

        # 1. Text match search
        stmt = (
            select(CodeChunk)
            .where(
                CodeChunk.repository_id == self.repository_id,
                CodeChunk.content.ilike(f"%{query}%"),
            )
            .limit(top_k * 2)
        )
        result = await self.session.execute(stmt)
        text_chunks = result.scalars().all()

        for chunk in text_chunks:
            hits[chunk.id] = CodeHit(
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                score=0.8,
                content=chunk.content,
                chunk_type=str(chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type),
                symbol_name=chunk.symbol_name,
                language=chunk.language,
                source="keyword",
                reason=f"Keyword match for '{query}' in file",
            )

        # 2. Semantic vector search if embedder available
        if self.embedder:
            try:
                emb_res = await self.embedder.embed([query])
                if emb_res.vectors:
                    q_vector = emb_res.vectors[0]
                    # Select embedded chunks
                    vec_stmt = (
                        select(CodeChunk)
                        .where(
                            CodeChunk.repository_id == self.repository_id,
                            CodeChunk.embedding.isnot(None),
                        )
                        .limit(100)
                    )
                    v_res = await self.session.execute(vec_stmt)
                    all_vec_chunks = v_res.scalars().all()

                    scored: list[tuple[float, CodeChunk]] = []
                    for c in all_vec_chunks:
                        if c.embedding is not None:
                            score = cosine_similarity(q_vector, c.embedding)
                            scored.append((score, c))

                    scored.sort(key=lambda x: x[0], reverse=True)
                    for score, chunk in scored[:top_k]:
                        prev = hits.get(chunk.id)
                        combined_score = (prev.score * 0.5 + score * 0.5) if prev else score
                        reason_str = (
                            f"Hybrid keyword and semantic vector match (score {combined_score:.2f})"
                            if prev
                            else f"Semantic vector similarity (score {score:.2f}) to query"
                        )
                        hits[chunk.id] = CodeHit(
                            path=chunk.path,
                            start_line=chunk.start_line,
                            end_line=chunk.end_line,
                            score=combined_score,
                            content=chunk.content,
                            chunk_type=str(
                                chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type
                            ),
                            symbol_name=chunk.symbol_name,
                            language=chunk.language,
                            source="hybrid" if prev else "vector",
                            reason=reason_str,
                        )
            except Exception as exc:
                logger.warning("vector_search_failed", error=str(exc))

        sorted_hits = sorted(hits.values(), key=lambda h: h.score, reverse=True)
        return sorted_hits[:top_k]

    async def symbol_lookup(self, name: str, *, limit: int = 10) -> list[CodeHit]:
        """Look up symbols by name and return matching code regions."""
        stmt = (
            select(Symbol, RepoFile)
            .join(RepoFile, Symbol.file_id == RepoFile.id)
            .where(
                Symbol.repository_id == self.repository_id,
                Symbol.name.ilike(f"%{name}%"),
            )
            .limit(limit)
        )
        res = await self.session.execute(stmt)
        rows = res.all()

        hits: list[CodeHit] = []
        for symbol, repo_file in rows:
            # Look for corresponding chunk or construct hit
            chunk_stmt = (
                select(CodeChunk)
                .where(
                    CodeChunk.file_id == repo_file.id,
                    CodeChunk.symbol_name == symbol.name,
                )
                .limit(1)
            )
            c_res = await self.session.execute(chunk_stmt)
            chunk = c_res.scalar_one_or_none()

            content = chunk.content if chunk else (symbol.signature or f"Symbol {symbol.name}")
            is_exact = symbol.name.lower() == name.lower()
            hits.append(
                CodeHit(
                    path=repo_file.path,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    score=1.0 if is_exact else 0.85,
                    content=content,
                    chunk_type=str(symbol.kind.value if hasattr(symbol.kind, "value") else symbol.kind),
                    symbol_name=symbol.name,
                    language=repo_file.language,
                    source="symbol",
                    reason=f"Matched symbol '{symbol.name}' ({'exact' if is_exact else 'partial'})",
                )
            )
        return hits

    async def retrieve_task_context(
        self,
        task_title: str,
        task_description: str,
        target_files: list[str] | None = None,
        top_k: int = 8,
    ) -> list[CodeHit]:
        """Multi-stage ranked retrieval of relevant code context for a task.

        1. Explicit target files match
        2. Extracted symbol names lookup
        3. Semantic vector search on task description
        4. Keyword search on key technical terms
        5. Evidence deduplication and ranking
        """
        import re

        collected: dict[tuple[str, int, int], CodeHit] = {}

        # 1. Explicit target files
        if target_files:
            for tf in target_files:
                tf_clean = tf.strip().replace("\\", "/")
                stmt = (
                    select(CodeChunk)
                    .where(
                        CodeChunk.repository_id == self.repository_id,
                        CodeChunk.path.ilike(f"%{tf_clean}%"),
                    )
                    .limit(4)
                )
                res = await self.session.execute(stmt)
                for chunk in res.scalars().all():
                    key = (chunk.path, chunk.start_line, chunk.end_line)
                    collected[key] = CodeHit(
                        path=chunk.path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        score=1.0,
                        content=chunk.content,
                        chunk_type=str(chunk.chunk_type.value if hasattr(chunk.chunk_type, "value") else chunk.chunk_type),
                        symbol_name=chunk.symbol_name,
                        language=chunk.language,
                        source="target_file",
                        reason=f"Explicit target file specified in task: {tf_clean}",
                    )

        # 2. Extract potential symbol identifiers from title and description
        combined_text = f"{task_title} {task_description}"
        identifiers = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", combined_text)
        # Filter out common English stop words
        common_words = {
            "the", "and", "for", "with", "that", "this", "from", "when", "into",
            "task", "test", "issue", "bug", "code", "file", "fix", "update", "create"
        }
        candidate_symbols = [w for w in set(identifiers) if w.lower() not in common_words][:5]
        for sym in candidate_symbols:
            sym_hits = await self.symbol_lookup(sym, limit=3)
            for h in sym_hits:
                key = (h.path, h.start_line, h.end_line)
                if key not in collected or collected[key].score < h.score:
                    collected[key] = h

        # 3. Hybrid search (semantic + keyword)
        query = f"{task_title} {task_description[:300]}".strip()
        search_hits = await self.search(query, top_k=top_k)
        for h in search_hits:
            key = (h.path, h.start_line, h.end_line)
            if key not in collected:
                collected[key] = h
            else:
                # Boost existing hit
                old_hit = collected[key]
                new_score = min(1.0, old_hit.score + 0.1)
                collected[key] = CodeHit(
                    path=old_hit.path,
                    start_line=old_hit.start_line,
                    end_line=old_hit.end_line,
                    score=new_score,
                    content=old_hit.content,
                    chunk_type=old_hit.chunk_type,
                    symbol_name=old_hit.symbol_name or h.symbol_name,
                    language=old_hit.language,
                    source=f"{old_hit.source}+hybrid",
                    reason=f"{old_hit.reason}; confirmed by semantic search",
                )

        # Sort by score descending and return top_k
        ranked = sorted(collected.values(), key=lambda x: x.score, reverse=True)
        return ranked[:top_k]

