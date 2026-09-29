"""Git inspection tools for repository state and diffs."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.permissions import Permission


class GitStatusArgs(BaseModel):
    short: bool = Field(default=True, description="Whether to show short format status")


class GitStatusTool(Tool):
    name = "git_status"
    description = "Inspect changed, untracked, and staged files in the repository working copy."
    permission = Permission.READ
    args_model = GitStatusArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, GitStatusArgs):
            return ToolResult.failure("Internal error: unexpected argument model")

        cmd = ["git", "status", "-s"] if args.short else ["git", "status"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ctx.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            return ToolResult.failure("git binary is not available on host")
        except OSError as exc:
            return ToolResult.failure(f"Failed to run git status: {exc}")

        if proc.returncode != 0:
            return ToolResult.failure(stderr.decode("utf-8", errors="replace").strip() or "git status failed")

        output = stdout.decode("utf-8", errors="replace").strip()
        return ToolResult.success(output or "Working tree clean", clean=not bool(output))


class GitDiffArgs(BaseModel):
    path: str | None = Field(default=None, description="Optional path to restrict diff to")
    cached: bool = Field(default=False, description="Whether to diff staged changes (--cached)")


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Generate a unified diff of unstaged or staged changes in the workspace."
    permission = Permission.READ
    args_model = GitDiffArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, GitDiffArgs):
            return ToolResult.failure("Internal error: unexpected argument model")

        cmd = ["git", "diff"]
        if args.cached:
            cmd.append("--cached")
        if args.path:
            cmd.extend(["--", args.path])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(ctx.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            return ToolResult.failure("git binary is not available on host")
        except OSError as exc:
            return ToolResult.failure(f"Failed to run git diff: {exc}")

        if proc.returncode != 0:
            return ToolResult.failure(stderr.decode("utf-8", errors="replace").strip() or "git diff failed")

        diff = stdout.decode("utf-8", errors="replace").strip()
        return ToolResult.success(diff or "(no changes)", has_changes=bool(diff))
