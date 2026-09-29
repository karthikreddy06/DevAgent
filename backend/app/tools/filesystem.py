"""Filesystem tools: read-only views of the task workspace.

There is deliberately no agent-facing write tool in the MVP. Code changes are
applied by the approval-gated change service after a human decision, so an agent
has no code path that can modify a file (see docs/architecture/security.md).
"""

from __future__ import annotations

import fnmatch
from typing import Any

from pydantic import BaseModel, Field

from app.core.errors import ValidationError
from app.core.ignore import IgnoreMatcher, load_ignore_matcher
from app.core.paths import safe_join
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.permissions import Permission

_HARD_MATCHER = IgnoreMatcher()
_MAX_WALK_FILES = 20_000


def is_credential_file(relative_path: str) -> bool:
    """True for paths that must never be read by an agent (.env, *.pem, ...)."""
    return _HARD_MATCHER.reason(relative_path, is_dir=False) == "potential credential file"


class ReadFileArgs(BaseModel):
    path: str = Field(description="Repository-relative path, POSIX separators, e.g. 'app/auth.py'")
    start_line: int | None = Field(default=None, ge=1, description="First line to include (1-based)")
    end_line: int | None = Field(default=None, ge=1, description="Last line to include (inclusive)")


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read a text file from the repository working copy. Output lines are prefixed with line numbers."
    permission = Permission.READ
    args_model = ReadFileArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, ReadFileArgs):  # pragma: no cover - registry guarantees the type
            return ToolResult.failure("Internal error: unexpected argument model")
        if is_credential_file(args.path):
            return ToolResult.failure(
                "Refused: this path looks like a credential file and is never readable by agents",
                path=args.path,
            )

        try:
            target = safe_join(ctx.workspace, args.path)
        except ValidationError as exc:
            return ToolResult.failure(exc.message, path=args.path)

        if not target.exists() or not target.is_file():
            return ToolResult.failure("File not found in the repository working copy", path=args.path)

        size = target.stat().st_size
        if size > ctx.settings.index_max_file_bytes:
            return ToolResult.failure(
                "File is too large to read",
                path=args.path,
                size_bytes=size,
                limit=ctx.settings.index_max_file_bytes,
            )

        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        total = len(lines)
        if total == 0:
            return ToolResult.success("(file is empty)", path=args.path, total_lines=0)
        start = max(1, args.start_line or 1)
        if start > total:
            return ToolResult.failure("start_line is past the end of the file", path=args.path, total_lines=total)
        end = min(total, args.end_line or total)
        numbered = "\n".join(f"{number:>5} | {line}" for number, line in enumerate(lines[start - 1 : end], start=start))
        return ToolResult.success(numbered, path=args.path, start_line=start, end_line=end, total_lines=total)


class ListFilesArgs(BaseModel):
    path: str = Field(default=".", description="Directory to list, relative to the repository root")
    pattern: str | None = Field(default=None, description="Optional glob, e.g. '**/test_*.py' or '*.py'")
    limit: int = Field(default=300, ge=1, le=2000)


class ListFilesTool(Tool):
    name = "list_files"
    description = "List repository files (honours .gitignore, .devagentignore and hard-coded secret/binary rules)."
    permission = Permission.READ
    args_model = ListFilesArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, ListFilesArgs):  # pragma: no cover - registry guarantees the type
            return ToolResult.failure("Internal error: unexpected argument model")

        matcher = load_ignore_matcher(ctx.workspace)
        base = ctx.workspace
        if args.path not in (".", "", "/"):
            try:
                base = safe_join(ctx.workspace, args.path)
            except ValidationError as exc:
                return ToolResult.failure(exc.message, path=args.path)
        if not base.exists():
            return ToolResult.failure("Directory not found", path=args.path)

        entries: list[str] = []
        scanned = 0
        for item in sorted(base.rglob("*")):
            if scanned >= _MAX_WALK_FILES:
                break
            if item.is_dir():
                continue
            relative = item.relative_to(ctx.workspace).as_posix()
            if matcher.is_ignored(relative, is_dir=False):
                continue
            scanned += 1
            if args.pattern and not (
                fnmatch.fnmatchcase(relative, args.pattern) or fnmatch.fnmatchcase(item.name, args.pattern)
            ):
                continue
            entries.append(f"{relative} ({item.stat().st_size} bytes)")
            if len(entries) >= args.limit:
                break

        if not entries:
            return ToolResult.success("No matching files", path=args.path, scanned_files=scanned)
        header: Any = f"{len(entries)} file(s) (of {scanned} scanned):"
        return ToolResult.success("\n".join([header, *entries]), path=args.path, scanned_files=scanned)
