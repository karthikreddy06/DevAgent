"""Sandboxed execution tools (require EXECUTE permission and docker sandbox)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.permissions import Permission


class RunCommandArgs(BaseModel):
    command: list[str] = Field(description="Command and arguments list to execute, e.g. ['pytest', '-v']")
    purpose: str = Field(description="Explanation of why this command is being run")
    cwd: str = Field(default="/workspace", description="Working directory inside container")
    timeout_seconds: int = Field(default=120, ge=1, le=300)


class RunCommandTool(Tool):
    name = "run_command"
    description = (
        "Execute a safe command inside the isolated docker sandbox container. "
        "Allows running tests, linters, or diagnostics. Requires EXECUTE permission."
    )
    permission = Permission.EXECUTE
    sandboxed = True
    args_model = RunCommandArgs

    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        if not isinstance(args, RunCommandArgs):
            return ToolResult.failure("Internal error: unexpected argument model")
        if ctx.sandbox is None:
            return ToolResult.failure("Sandbox executor is not available for this run")

        output = await ctx.sandbox.execute(
            args.command,
            purpose=args.purpose,
            cwd=args.cwd,
            timeout_seconds=args.timeout_seconds,
            agent=ctx.agent,
        )

        if ctx.session is not None and ctx.task_id is not None:
            try:
                from app.models.enums import AgentName, RunStatus
                from app.models.sandbox import SandboxRun

                agent_val = AgentName.DEBUGGER
                try:
                    agent_val = AgentName(ctx.agent)
                except Exception:
                    pass

                s_run = SandboxRun(
                    task_id=ctx.task_id,
                    agent=agent_val,
                    purpose=args.purpose[:60],
                    image=getattr(ctx.sandbox, "_image", ctx.settings.sandbox_image),
                    container_id=getattr(ctx.sandbox, "container_id", None),
                    command=args.command,
                    cwd=args.cwd,
                    status=RunStatus.SUCCEEDED if output.ok else RunStatus.FAILED,
                    exit_code=output.exit_code,
                    timed_out=output.timed_out,
                    duration_ms=output.duration_ms,
                    stdout_ref=(output.stdout or "")[:1000],
                    stderr_ref=(output.stderr or "")[:1000],
                )
                ctx.session.add(s_run)
                await ctx.session.flush()
            except Exception:
                pass

        if output.ok:
            return ToolResult.success(
                output.summary(),
                exit_code=output.exit_code,
                duration_ms=output.duration_ms,
                stdout=output.stdout,
                stderr=output.stderr,
            )

        return ToolResult.failure(
            output.summary(),
            exit_code=output.exit_code,
            duration_ms=output.duration_ms,
            timed_out=output.timed_out,
            oom_killed=output.oom_killed,
            details=output.error,
        )
