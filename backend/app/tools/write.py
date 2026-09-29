"""Filesystem write and patch tools (require WRITE permission)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.errors import PolicyViolationError, ValidationError
from app.core.paths import safe_join
from app.models.enums import TaskStatus
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.filesystem import is_credential_file
from app.tools.permissions import Permission


class WriteFileArgs(BaseModel):
    path: str = Field(description="Relative file path inside the repository workspace")
    content: str = Field(description="Full text content to write to the file")
    overwrite: bool = Field(default=True, description="Whether to overwrite existing file")


class WriteFileTool(Tool):
    name = "write_file"
    description = "Create or overwrite a file in the repository workspace. Requires WRITE permission."
    permission = Permission.WRITE
    args_model = WriteFileArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, WriteFileArgs):
            return ToolResult.failure("Internal error: unexpected argument model")
        if is_credential_file(args.path):
            return ToolResult.failure("Refused: writing credential or sensitive files is prohibited", path=args.path)

        task_status = getattr(ctx, "task_status", None)
        if task_status != TaskStatus.APPLYING:
            return ToolResult.failure(
                f"Write rejected: Task must be in APPLYING status with an approved change, but got {task_status.value if task_status else 'None'}",
                path=args.path,
            )

        try:
            target = safe_join(ctx.workspace, args.path)
        except (ValidationError, PolicyViolationError) as exc:
            return ToolResult.failure(str(exc), path=args.path)

        if target.exists() and not args.overwrite:
            return ToolResult.failure("File already exists and overwrite is false", path=args.path)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Failed to write file: {exc}", path=args.path)

        lines = len(args.content.splitlines())
        return ToolResult.success(
            f"Successfully wrote {lines} lines to {args.path}",
            path=args.path,
            lines=lines,
            size_bytes=len(args.content.encode("utf-8")),
        )


class ApplyPatchArgs(BaseModel):
    path: str = Field(description="Relative file path inside the repository workspace to modify")
    old_str: str = Field(description="Exact snippet of code to be replaced")
    new_str: str = Field(description="New snippet of code to insert in place of old_str")


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Replace a unique code snippet with new code in a repository file. Requires WRITE permission."
    permission = Permission.WRITE
    args_model = ApplyPatchArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, ApplyPatchArgs):
            return ToolResult.failure("Internal error: unexpected argument model")

        task_status = getattr(ctx, "task_status", None)
        if task_status != TaskStatus.APPLYING:
            return ToolResult.failure(
                f"Write rejected: Task must be in APPLYING status with an approved change, but got {task_status.value if task_status else 'None'}",
                path=args.path,
            )

        try:
            target = safe_join(ctx.workspace, args.path)
        except (ValidationError, PolicyViolationError) as exc:
            return ToolResult.failure(str(exc), path=args.path)

        if not target.is_file():
            return ToolResult.failure("Target file not found", path=args.path)

        content = target.read_text(encoding="utf-8", errors="replace")
        count = content.count(args.old_str)
        if count == 0:
            return ToolResult.failure("old_str not found in target file", path=args.path)
        if count > 1:
            return ToolResult.failure(
                f"old_str occurs {count} times in target file; replacement must be unique",
                path=args.path,
                occurrences=count,
            )

        new_content = content.replace(args.old_str, args.new_str, 1)
        try:
            target.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return ToolResult.failure(f"Failed to save modified file: {exc}", path=args.path)

        return ToolResult.success(
            f"Successfully replaced snippet in {args.path}",
            path=args.path,
            replaced_bytes=len(args.old_str),
            new_bytes=len(args.new_str),
        )


class ProposePatchArgs(BaseModel):
    path: str = Field(description="Relative file path inside the repository workspace to modify or create")
    old_str: str = Field(default="", description="Exact snippet of code to be replaced, or empty string if creating a new file")
    new_str: str = Field(description="New snippet of code to insert in place of old_str, or full content of new file")
    explanation: str = Field(default="", description="Explanation of why this change fixes the issue")
    is_new_file: bool = Field(default=False, description="True if proposing to add a brand new file")


class ProposePatchTool(Tool):
    name = "propose_patch"
    description = (
        "Propose a code fix for human review and approval. "
        "Validates that the target file exists (or is marked as new) and computes a clean diff without modifying the workspace yet. "
        "Use this tool when you have diagnosed the bug and formulated the exact fix."
    )
    permission = Permission.READ
    args_model = ProposePatchArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        import difflib

        if not isinstance(args, ProposePatchArgs):
            return ToolResult.failure("Internal error: unexpected argument model")

        try:
            target = safe_join(ctx.workspace, args.path)
        except (ValidationError, PolicyViolationError) as exc:
            return ToolResult.failure(str(exc), path=args.path)

        is_new = args.is_new_file or (not target.exists() and args.old_str == "")

        if is_new:
            content = ""
            new_content = args.new_str
            diff_lines = list(
                difflib.unified_diff(
                    [],
                    new_content.splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"b/{args.path}",
                )
            )
            change_type_str = "add"
        else:
            if not target.is_file():
                return ToolResult.failure("Target file not found", path=args.path)

            content = target.read_text(encoding="utf-8", errors="replace")
            count = content.count(args.old_str)
            if count == 0:
                return ToolResult.failure("old_str not found in target file", path=args.path)
            if count > 1:
                return ToolResult.failure(
                    f"old_str occurs {count} times in target file; replacement must be unique",
                    path=args.path,
                    occurrences=count,
                )

            new_content = content.replace(args.old_str, args.new_str, 1)
            diff_lines = list(
                difflib.unified_diff(
                    content.splitlines(keepends=True),
                    new_content.splitlines(keepends=True),
                    fromfile=f"a/{args.path}",
                    tofile=f"b/{args.path}",
                )
            )
            change_type_str = "modify"

        unified_diff = "".join(diff_lines)

        patch_info = {
            "path": args.path,
            "old_str": args.old_str,
            "new_str": args.new_str,
            "explanation": args.explanation,
            "unified_diff": unified_diff,
            "original_content": content if not is_new else None,
            "proposed_content": new_content,
            "change_type": change_type_str,
        }

        ctx.proposed_patch = patch_info
        if hasattr(ctx, "proposed_patches"):
            # Update existing proposal for same path or append
            replaced = False
            for i, p in enumerate(ctx.proposed_patches):
                if p.get("path") == args.path:
                    ctx.proposed_patches[i] = patch_info
                    replaced = True
                    break
            if not replaced:
                ctx.proposed_patches.append(patch_info)

        return ToolResult.success(
            f"Fix proposed successfully for {args.path}. Requires human approval before applying.\nDiff:\n{unified_diff}",
            path=args.path,
            diff=unified_diff,
        )

