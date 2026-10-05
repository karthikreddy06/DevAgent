"""Tool contracts: what a tool is, what it may touch, and what it returns."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from app.core.config import Settings
from app.core.redaction import truncate_text
from app.models.enums import AgentName, TaskStatus
from app.tools.permissions import Permission

DEFAULT_TOOL_OUTPUT_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class CodeHit:
    """A retrieval hit returned by the code search service."""

    path: str
    start_line: int
    end_line: int
    score: float
    content: str
    chunk_type: str = "window"
    symbol_name: str | None = None
    language: str = "unknown"
    source: str = "hybrid"
    reason: str = ""


class CodeSearch(Protocol):
    """Retrieval interface injected into tools (implemented by the retriever)."""

    async def search(self, query: str, *, top_k: int = 8) -> list[CodeHit]: ...

    async def symbol_lookup(self, name: str, *, limit: int = 10) -> list[CodeHit]: ...


@dataclass(frozen=True, slots=True)
class SandboxOutput:
    """Result of a sandboxed execution."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    oom_killed: bool = False
    truncated: bool = False
    duration_ms: int = 0
    sandbox_run_id: uuid.UUID | None = None
    container_id: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and self.error is None

    def summary(self, *, limit: int = 2000) -> str:
        parts = [f"exit_code={self.exit_code}"]
        if self.timed_out:
            parts.append("timed_out=true")
        if self.oom_killed:
            parts.append("oom_killed=true")
        if self.error:
            parts.append(f"error={self.error}")
        if self.stdout.strip():
            parts.append(f"stdout:\n{truncate_text(self.stdout.strip(), limit)}")
        if self.stderr.strip():
            parts.append(f"stderr:\n{truncate_text(self.stderr.strip(), limit)}")
        return "\n".join(parts)


class SandboxExecutor(Protocol):
    """Sandbox interface injected into tools (implemented by the docker runner)."""

    async def execute(
        self,
        argv: Sequence[str],
        *,
        purpose: str,
        cwd: str = "/workspace",
        timeout_seconds: int | None = None,
        network_enabled: bool = False,
        session: Any = None,
        agent: AgentName | None = None,
    ) -> SandboxOutput: ...


@dataclass(frozen=True, slots=True)
class ToolResult:
    """What every tool returns to the agent loop."""

    ok: bool
    output: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    exit_code: int | None = None
    duration_ms: int = 0
    truncated: bool = False
    artifact_ref: str | None = None
    sandbox_run_id: uuid.UUID | None = None

    @classmethod
    def success(cls, output: str, *, exit_code: int | None = None, **data: Any) -> ToolResult:
        if exit_code is None and "exit_code" in data:
            exit_code = data.pop("exit_code")
        return cls(ok=True, output=output, exit_code=exit_code, data=data)

    @classmethod
    def failure(cls, error: str, *, exit_code: int | None = None, **data: Any) -> ToolResult:
        if exit_code is None and "exit_code" in data:
            exit_code = data.pop("exit_code")
        return cls(ok=False, error=error, exit_code=exit_code, data=data)

    def limited(self, max_chars: int) -> ToolResult:
        """Return a copy with the free-text output truncated."""
        if len(self.output) <= max_chars:
            return self
        return ToolResult(
            ok=self.ok,
            output=truncate_text(self.output, max_chars),
            data=self.data,
            error=self.error,
            exit_code=self.exit_code,
            duration_ms=self.duration_ms,
            truncated=True,
            artifact_ref=self.artifact_ref,
            sandbox_run_id=self.sandbox_run_id,
        )


EventEmitter = Callable[[str, str, dict[str, Any] | None], Awaitable[None]]


@dataclass(slots=True)
class ToolContext:
    """Everything a tool is allowed to touch.

    The context is built per agent run by the orchestrator, which is also where
    the sandbox, retrieval service and event emitter are injected. Tools never
    reach for global state.
    """

    task_id: uuid.UUID
    agent: AgentName
    workspace: Path
    settings: Settings
    search: CodeSearch | None = None
    sandbox: SandboxExecutor | None = None
    emit: EventEmitter | None = None
    session: Any = None  # SQLAlchemy AsyncSession when the tool persists rows
    max_output_chars: int = DEFAULT_TOOL_OUTPUT_CHARS
    proposed_patch: dict[str, Any] | None = None
    proposed_patches: list[dict[str, Any]] = field(default_factory=list)
    task_status: TaskStatus | None = None

    async def notify(self, event_type: str, message: str, payload: dict[str, Any] | None = None) -> None:
        if self.emit is not None:
            await self.emit(event_type, message, payload)


class Tool(ABC):
    """Base class for all tools."""

    name: str = "tool"
    description: str = ""
    permission: Permission = Permission.READ
    #: True when the tool must run commands inside the docker sandbox.
    sandboxed: bool = False

    @property
    @abstractmethod
    def args_model(self) -> type[BaseModel]:
        """Pydantic model validating this tool's arguments."""

    @abstractmethod
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        """Execute the tool. Implementations must not raise for expected failures."""

    def catalogue_entry(self) -> dict[str, Any]:
        properties = self.args_model.model_json_schema().get("properties", {})
        return {
            "name": self.name,
            "description": self.description,
            "permission": self.permission.value,
            "sandboxed": self.sandboxed,
            "args_schema": properties,
        }

    async def timed(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        """Run the tool, timing it and converting failures into ToolResults."""
        started = time.perf_counter()
        try:
            result = await self.run(args, ctx)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return ToolResult.failure(f"{self.name} failed: {type(exc).__name__}: {exc}", duration_ms=elapsed).limited(
                ctx.max_output_chars
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        return ToolResult(
            ok=result.ok,
            output=result.output,
            data=result.data,
            error=result.error,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms or elapsed,
            truncated=result.truncated,
            artifact_ref=result.artifact_ref,
            sandbox_run_id=result.sandbox_run_id,
        ).limited(ctx.max_output_chars)
