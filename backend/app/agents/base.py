"""Base agent implementation with step loop, tool execution, and audit logging."""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, PolicyViolationError
from app.core.logging import get_logger
from app.llm.base import LLMMessage, LLMProvider
from app.models.agent import AgentRun, AgentStep, ToolExecution
from app.models.enums import AgentName, RunStatus, StepKind
from app.models.task import Task
from app.orchestration.budgets import BudgetTracker
from app.tools.base import ToolContext, ToolResult
from app.tools.permissions import PermissionSet
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

# Matches ```json { "tool": "name", "args": {...} } ``` or { "tool": "...", "args": {...} }
_TOOL_CALL_RE = re.compile(r"```(?:json)?\s*(\{\s*\"tool\".*?\})\s*```", re.DOTALL)
MAX_TOOLS_PER_TURN = 4


def extract_tool_calls(text: str, max_per_turn: int | None = None) -> list[dict[str, Any]]:
    """Extract structured, deduplicated tool calls from agent LLM response.

    Filters malformed or empty tool blocks, deduplicates identical calls within the same turn,
    and optionally caps the number of calls per turn.
    """
    raw_calls: list[dict[str, Any]] = []

    # 1. Try markdown code block extraction
    for match in _TOOL_CALL_RE.finditer(text):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                raw_calls.append(data)
        except json.JSONDecodeError:
            continue

    # 2. Try raw JSON object search if no code blocks matched
    if not raw_calls:
        for match in re.finditer(r"\{\s*\"tool\"\s*:", text):
            start = match.start()
            try:
                brace_count = 0
                end = start
                for i in range(start, len(text)):
                    if text[i] == "{":
                        brace_count += 1
                    elif text[i] == "}":
                        brace_count -= 1
                        if brace_count == 0:
                            end = i + 1
                            break
                data = json.loads(text[start:end])
                if isinstance(data, dict):
                    raw_calls.append(data)
            except json.JSONDecodeError:
                pass

    # 3. Clean, validate, and deduplicate identical tool+arguments in the same turn
    validated_calls: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str]] = set()

    for item in raw_calls:
        tool_name = item.get("tool")
        if not isinstance(tool_name, str) or not tool_name.strip():
            continue
        tool_name = tool_name.strip()
        args = item.get("args")
        if isinstance(args, dict) and args:
            pass
        else:
            remaining = {k: v for k, v in item.items() if k not in ("tool", "args")}
            if remaining:
                args = remaining
            elif not isinstance(args, dict):
                args = {}

        try:
            serialized_args = json.dumps(args, sort_keys=True)
        except Exception:
            serialized_args = str(args)

        sig = (tool_name, serialized_args)
        if sig in seen_signatures:
            continue
        seen_signatures.add(sig)

        validated_calls.append(
            {
                "tool": tool_name,
                "args": args,
            }
        )

    if max_per_turn is not None and len(validated_calls) > max_per_turn:
        return validated_calls[:max_per_turn]

    return validated_calls


class BaseAgent(ABC):
    """Abstract base class for all DevAgent sub-agents."""

    name: AgentName
    system_prompt: str

    def __init__(self, llm: LLMProvider, registry: ToolRegistry) -> None:
        self.llm = llm
        self.registry = registry

    @abstractmethod
    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        """Construct the user prompt describing the agent's specific mission."""

    def get_recovery_prompt(
        self,
        task: Task,
        context: ToolContext,
        response_text: str,
        extra_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Hook for sub-agents to trigger a single recovery turn if needed."""
        return None

    def get_tool_error_correction_prompt(
        self,
        task: Task,
        context: ToolContext,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: ToolResult,
        extra_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Hook for specialized agents to provide targeted correction prompts when a tool fails."""
        return None

    def format_tools_catalog(self, capabilities: PermissionSet) -> str:
        catalogue = self.registry.catalogue(capabilities)
        entries = []
        for entry in catalogue:
            args_info = entry.get("args_schema") or entry.get("schema", {})
            entries.append(
                f"- Tool: `{entry['name']}` ({entry['permission']})\n"
                f"  Description: {entry['description']}\n"
                f"  Arguments: {json.dumps(args_info)}"
            )
        return "\n\n".join(entries)

    async def run(
        self,
        task: Task,
        context: ToolContext,
        capabilities: PermissionSet,
        budget: BudgetTracker,
        session: AsyncSession,
        extra_context: dict[str, Any] | None = None,
    ) -> str:
        """Execute the agent run loop, persisting AgentRun, AgentStep, and ToolExecution."""
        agent_run = AgentRun(
            task_id=task.id,
            agent=self.name,
            iteration=task.iteration,
            status=RunStatus.RUNNING,
            model=self.llm.model,
            provider=self.llm.name,
            prompt_tokens=0,
            completion_tokens=0,
            tool_calls=0,
            step_count=0,
            started_at=datetime_now_utc(),
        )
        session.add(agent_run)
        await session.flush()

        tools_desc = self.format_tools_catalog(capabilities)
        full_system = (
            f"{self.system_prompt}\n\n"
            f"AVAILABLE TOOLS:\n{tools_desc}\n\n"
            "To invoke a tool, respond with a JSON block:\n"
            "```json\n"
            '{\n  "tool": "tool_name",\n  "args": { ... }\n}\n'
            "```\n"
            "When you have finished your work or gathered enough information, give your final conclusion."
        )

        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=full_system),
            LLMMessage(role="user", content=self.build_initial_prompt(task, extra_context)),
        ]

        step_idx = 0
        final_answer = ""
        response = None
        recovery_attempted = False

        try:
            while budget.steps < budget.max_steps and (
                budget.current_stage is None or budget.stage_steps < budget.stage_max_steps
            ):
                budget.record_step()
                step_idx += 1
                t0 = time.perf_counter()

                response = await self.llm.complete(messages)
                latency = int((time.perf_counter() - t0) * 1000)
                budget.record_tokens(response.usage.prompt_tokens, response.usage.completion_tokens)

                agent_run.prompt_tokens += response.usage.prompt_tokens
                agent_run.completion_tokens += response.usage.completion_tokens
                agent_run.step_count = step_idx

                llm_step = AgentStep(
                    agent_run_id=agent_run.id,
                    task_id=task.id,
                    step_index=step_idx,
                    kind=StepKind.LLM,
                    args={"prompt": messages[-1].content[:2000]},
                    result_summary=response.text[:2000],
                    status=RunStatus.SUCCEEDED,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=latency,
                )
                session.add(llm_step)
                await session.flush()

                # Extract and deduplicate tool calls; cap at 4 per turn
                all_tools = extract_tool_calls(response.text, max_per_turn=None)
                if not all_tools:
                    recovery_prompt = self.get_recovery_prompt(task, context, response.text, extra_context)
                    if recovery_prompt and not recovery_attempted:
                        recovery_attempted = True
                        messages.append(LLMMessage(role="assistant", content=response.text))
                        messages.append(LLMMessage(role="user", content=recovery_prompt))
                        continue

                    final_answer = response.text
                    break

                tool_calls = all_tools[:MAX_TOOLS_PER_TURN]
                was_truncated = len(all_tools) > MAX_TOOLS_PER_TURN

                stage_budget_hit = False
                # Execute requested tools
                for tc in tool_calls:
                    t_name = tc.get("tool", "")
                    t_args = tc.get("args", {})

                    can_call = budget.record_tool_call()
                    if not can_call:
                        stage_budget_hit = True
                        break

                    agent_run.tool_calls += 1

                    t_start = time.perf_counter()
                    try:
                        t_result = await self.registry.execute(t_name, t_args, context, capabilities)
                    except (NotFoundError, PolicyViolationError) as exc:
                        from app.tools.base import ToolResult

                        t_result = ToolResult.failure(f"Tool error: {exc}", tool=t_name)
                    except Exception as exc:
                        logger.error("tool_execution_uncaught_error", tool=t_name, error=str(exc))
                        from app.tools.base import ToolResult

                        t_result = ToolResult.failure(f"Tool execution failed unexpectedly: {exc}", tool=t_name)
                    t_duration = int((time.perf_counter() - t_start) * 1000)

                    tool_exec = ToolExecution(
                        task_id=task.id,
                        agent_run_id=agent_run.id,
                        agent=self.name,
                        tool_name=t_name,
                        permission=capabilities.as_names()[0] if capabilities.as_names() else "READ",
                        args=t_args,
                        status=RunStatus.SUCCEEDED if t_result.ok else RunStatus.FAILED,
                        duration_ms=t_duration,
                        exit_code=t_result.exit_code,
                        stdout_preview=(t_result.output or "")[:3000] if t_result.ok else None,
                        stderr_preview=(t_result.error or "")[:3000] if not t_result.ok else None,
                        error=t_result.error,
                    )
                    session.add(tool_exec)

                    tool_step = AgentStep(
                        agent_run_id=agent_run.id,
                        task_id=task.id,
                        step_index=step_idx + 1,
                        kind=StepKind.TOOL,
                        tool_name=t_name,
                        args=t_args,
                        result_summary=(t_result.output or t_result.error or "")[:2000],
                        status=RunStatus.SUCCEEDED if t_result.ok else RunStatus.FAILED,
                        latency_ms=t_duration,
                    )
                    session.add(tool_step)
                    step_idx += 1

                    # Append tool result to dialogue
                    if not t_result.ok:
                        correction = self.get_tool_error_correction_prompt(
                            task, context, t_name, t_args, t_result, extra_context
                        )
                        if correction:
                            content_str = (
                                f"TOOL ERROR ({t_name}):\n{t_result.error}\n\n"
                                f"CORRECTION REQUIRED:\n{correction}"
                            )
                        else:
                            content_str = f"TOOL ERROR ({t_name}):\n{t_result.error}"
                    else:
                        content_str = f"TOOL RESULT ({t_name}):\n{t_result.output}"

                    messages.append(LLMMessage(role="assistant", content=f"Executed tool {t_name}"))
                    messages.append(LLMMessage(role="user", content=content_str))

                if stage_budget_hit:
                    messages.append(
                        LLMMessage(
                            role="user",
                            content="[TOOL BUDGET NOTICE: You have reached the tool call limit for this phase. Do not invoke more tools. Synthesize the gathered facts and output your final conclusion now.]",
                        )
                    )
                elif was_truncated:
                    messages.append(
                        LLMMessage(
                            role="user",
                            content=f"[Notice: Bounded to {MAX_TOOLS_PER_TURN} tool calls for this turn ({len(all_tools) - MAX_TOOLS_PER_TURN} speculative calls omitted). Please evaluate the above results before making further calls.]",
                        )
                    )

                await session.flush()

            if not final_answer and response and response.text:
                final_answer = response.text

            agent_run.status = RunStatus.SUCCEEDED
            agent_run.summary = final_answer[:2000]
            agent_run.budget_usage = budget.to_dict()
            agent_run.finished_at = datetime_now_utc()
            await session.commit()
            return final_answer

        except Exception as exc:
            agent_run.status = RunStatus.FAILED
            agent_run.error = str(exc)
            agent_run.finished_at = datetime_now_utc()
            agent_run.budget_usage = budget.to_dict()
            await session.commit()
            raise


def datetime_now_utc() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)
