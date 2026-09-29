"""Tool registry and built-in tools."""

from app.tools.base import CodeHit, CodeSearch, SandboxExecutor, SandboxOutput, Tool, ToolContext, ToolResult
from app.tools.execution import RunCommandTool
from app.tools.filesystem import ListFilesTool, ReadFileTool
from app.tools.git import GitDiffTool, GitStatusTool
from app.tools.permissions import INVESTIGATION, READ_ONLY, Permission, PermissionSet, permissions_for_status
from app.tools.registry import ToolRegistry
from app.tools.search import FindSymbolTool, SearchCodebaseTool, SearchInFilesTool
from app.tools.write import ApplyPatchTool, ProposePatchTool, WriteFileTool


def create_default_registry() -> ToolRegistry:
    """Build a ToolRegistry loaded with all built-in DevAgent tools."""
    return ToolRegistry(
        [
            ReadFileTool(),
            ListFilesTool(),
            SearchInFilesTool(),
            SearchCodebaseTool(),
            FindSymbolTool(),
            WriteFileTool(),
            ApplyPatchTool(),
            ProposePatchTool(),
            RunCommandTool(),
            GitStatusTool(),
            GitDiffTool(),
        ]
    )


__all__ = [
    "INVESTIGATION",
    "READ_ONLY",
    "ApplyPatchTool",
    "CodeHit",
    "CodeSearch",
    "FindSymbolTool",
    "GitDiffTool",
    "GitStatusTool",
    "ListFilesTool",
    "Permission",
    "PermissionSet",
    "ReadFileTool",
    "RunCommandTool",
    "SandboxExecutor",
    "SandboxOutput",
    "SearchCodebaseTool",
    "SearchInFilesTool",
    "Tool",
    "ToolContext",
    "ToolRegistry",
    "ToolResult",
    "WriteFileTool",
    "create_default_registry",
    "permissions_for_status",
]
