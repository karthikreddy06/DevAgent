"""Tool registry with permission enforcement.

The registry is the *gate*: a tool whose permission is not present in the
current capability set cannot be looked up, so an agent cannot call it even if
it invents the name. Argument validation happens here too, and a validation
failure is returned as a normal tool result so the agent can correct itself
inside its step budget.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from app.core.errors import NotFoundError, PolicyViolationError
from app.models.enums import TaskStatus
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.permissions import Permission, PermissionSet


class ToolRegistry:
    """A named collection of tools plus the capability check."""

    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise NotFoundError("Unknown tool", details={"tool": name}) from exc

    def all_tools(self) -> Sequence[Tool]:
        return tuple(self._tools.values())

    def available(self, capabilities: PermissionSet) -> list[Tool]:
        """Tools the current capability set permits (order is stable)."""
        return [tool for tool in self._tools.values() if capabilities.allows(tool.permission)]

    def catalogue(self, capabilities: PermissionSet) -> list[dict[str, Any]]:
        return [tool.catalogue_entry() for tool in self.available(capabilities)]

    def tool_names(self, capabilities: PermissionSet) -> list[str]:
        return [tool.name for tool in self.available(capabilities)]

    def check(self, name: str, capabilities: PermissionSet) -> Tool:
        """Return the tool if permitted, else raise."""
        tool = self.get(name)
        if not capabilities.allows(tool.permission):
            raise PolicyViolationError(
                f"Tool '{name}' requires the {tool.permission.value} permission, which is not granted",
                details={"tool": name, "required": tool.permission.value, "granted": capabilities.as_names()},
            )
        return tool

    async def execute(
        self,
        name: str,
        raw_args: dict[str, Any],
        ctx: ToolContext,
        capabilities: PermissionSet,
    ) -> ToolResult:
        """Validate, authorise and run a tool call."""
        tool = self.check(name, capabilities)

        if tool.permission == Permission.WRITE:
            task_status = getattr(ctx, "task_status", None)
            if task_status != TaskStatus.APPLYING:
                raise PolicyViolationError(
                    f"Tool '{name}' requires task to be in the explicitly authorized APPLYING status, "
                    f"but current status is {task_status.value if task_status else 'None'}",
                    details={
                        "tool": name,
                        "required_status": TaskStatus.APPLYING.value,
                        "current_status": task_status.value if task_status else None,
                    },
                )

        try:
            args = tool.args_model.model_validate(raw_args)
        except PydanticValidationError as exc:
            problems = [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]
            return ToolResult.failure(
                f"Invalid arguments for {name}: {'; '.join(problems)}",
                tool=name,
                validation_errors=problems,
            )

        if tool.sandboxed and ctx.sandbox is None:
            return ToolResult.failure(
                f"{name} requires the docker sandbox, which is not available in this run",
                tool=name,
            )

        return await tool.timed(args, ctx)
