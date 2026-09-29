"""Search tools: exact regex search, hybrid retrieval and symbol lookup.

``search_codebase`` is the retrieval entry point agents should prefer: it uses
the indexed, embedded chunks (vector + full-text fusion) instead of dumping files
into the prompt. ``search_in_files`` stays available for exact literal hunting
when the query is not semantic.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import ValidationError
from app.core.ignore import load_ignore_matcher
from app.core.paths import safe_join
from app.tools.base import CodeHit, Tool, ToolContext, ToolResult
from app.tools.permissions import Permission

_MAX_REGEX_LENGTH = 300


class SearchInFilesArgs(BaseModel):
    query: str = Field(description="Python regular expression to search for")
    path: str | None = Field(default=None, description="Limit the search to this directory")
    file_pattern: str | None = Field(default=None, description="Glob filter applied to file names, e.g. '*.py'")
    ignore_case: bool = Field(default=True)
    max_results: int = Field(default=40, ge=1, le=200)
    context_lines: int = Field(default=2, ge=0, le=8)


class SearchInFilesTool(Tool):
    name = "search_in_files"
    description = "Regex search across repository text files. Returns path:line matches with context lines."
    permission = Permission.READ
    args_model = SearchInFilesArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, SearchInFilesArgs):  # pragma: no cover
            return ToolResult.failure("Internal error: unexpected argument model")
        if len(args.query) > _MAX_REGEX_LENGTH:
            return ToolResult.failure("Query is too long", max_length=_MAX_REGEX_LENGTH)
        try:
            pattern = re.compile(args.query, re.IGNORECASE if args.ignore_case else 0)
        except re.error as exc:
            return ToolResult.failure(f"Invalid regular expression: {exc}")

        matcher = load_ignore_matcher(ctx.workspace)
        base = ctx.workspace
        if args.path:
            try:
                base = safe_join(ctx.workspace, args.path)
            except ValidationError as exc:
                return ToolResult.failure(exc.message, path=args.path)
        if not base.exists():
            return ToolResult.failure("Search path not found", path=args.path)

        matches: list[str] = []
        scanned = 0
        for item in sorted(base.rglob("*")):
            if not item.is_file():
                continue
            relative = item.relative_to(ctx.workspace).as_posix()
            if matcher.is_ignored(relative, is_dir=False):
                continue
            if args.file_pattern and not fnmatch.fnmatchcase(item.name, args.file_pattern):
                continue
            if item.stat().st_size > ctx.settings.index_max_file_bytes:
                continue
            scanned += 1
            lines = item.read_text(encoding="utf-8", errors="replace").splitlines()
            for index, line in enumerate(lines):
                if not pattern.search(line):
                    continue
                low = max(0, index - args.context_lines)
                high = min(len(lines), index + args.context_lines + 1)
                block = [f"{relative}:{number + 1}: {lines[number].strip()[:300]}" for number in range(low, high)]
                matches.append("\n".join(block))
                if len(matches) >= args.max_results:
                    break
            if len(matches) >= args.max_results:
                break

        if not matches:
            return ToolResult.success("No matches", query=args.query, scanned_files=scanned)
        header = f"{len(matches)} match group(s) across {scanned} files:"
        return ToolResult.success("\n\n".join([header, *matches]), query=args.query, match_groups=len(matches))


def format_hits(hits: list[CodeHit], *, body_chars: int = 900) -> str:
    """Render retrieval hits as compact, citable text."""
    blocks: list[str] = []
    for hit in hits:
        label = f"{hit.path}:{hit.start_line}-{hit.end_line}"
        if hit.symbol_name:
            label += f" [{hit.chunk_type}:{hit.symbol_name}]"
        else:
            label += f" [{hit.chunk_type}]"
        blocks.append(f"{label} (score={hit.score:.3f})\n{hit.content[:body_chars]}")
    return "\n\n".join(blocks)


class SearchCodebaseArgs(BaseModel):
    query: str = Field(description="Natural-language or code-like query, e.g. 'where is the token validated'")
    top_k: int = Field(default=8, ge=1, le=25)


class SearchCodebaseTool(Tool):
    name = "search_codebase"
    description = (
        "Semantic + keyword hybrid search over the indexed repository. Returns relevant code chunks with "
        "file path and line range. Prefer this over reading whole files."
    )
    permission = Permission.READ
    args_model = SearchCodebaseArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, SearchCodebaseArgs):  # pragma: no cover
            return ToolResult.failure("Internal error: unexpected argument model")
        if ctx.search is None:
            return ToolResult.failure("Codebase index is not available for this run")
        hits = await ctx.search.search(args.query, top_k=args.top_k)
        if not hits:
            return ToolResult.success(
                "No indexed matches. The repository may not be indexed yet, or the query has no close match.",
                query=args.query,
                hits=0,
            )
        return ToolResult.success(
            format_hits(hits),
            query=args.query,
            hits=len(hits),
            citations=[f"{hit.path}:{hit.start_line}-{hit.end_line}" for hit in hits],
        )


class FindSymbolArgs(BaseModel):
    name: str = Field(description="Symbol name or fragment, e.g. 'validate_token' or 'AuthService'")
    limit: int = Field(default=10, ge=1, le=50)


class FindSymbolTool(Tool):
    name = "find_symbol"
    description = "Locate functions/classes/methods by name in the indexed repository."
    permission = Permission.READ
    args_model = FindSymbolArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, FindSymbolArgs):  # pragma: no cover
            return ToolResult.failure("Internal error: unexpected argument model")
        if ctx.search is None:
            return ToolResult.failure("Codebase index is not available for this run")
        hits = await ctx.search.symbol_lookup(args.name, limit=args.limit)
        if not hits:
            return ToolResult.success(f"No symbol matching {args.name!r} was found", name=args.name, hits=0)
        return ToolResult.success(format_hits(hits), name=args.name, hits=len(hits))


def summarise_hits(hits: list[CodeHit]) -> list[dict[str, Any]]:
    """JSON-serialisable hit list (used by the chat API citations)."""
    return [
        {
            "path": hit.path,
            "start_line": hit.start_line,
            "end_line": hit.end_line,
            "score": round(hit.score, 4),
            "chunk_type": hit.chunk_type,
            "symbol": hit.symbol_name,
            "language": hit.language,
        }
        for hit in hits
    ]
