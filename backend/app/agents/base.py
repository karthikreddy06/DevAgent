"""Base agent implementation with step loop, tool execution, and audit logging."""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.llm.base import LLMMessage, LLMProvider
from app.models.agent import AgentRun, AgentStep, ToolExecution
from app.models.enums import AgentName, RunStatus, StepKind
from app.models.task import Task
from app.orchestration.budgets import BudgetTracker
from app.tools.base import ToolContext
from app.tools.permissions import PermissionSet
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)

# Matches ```json { "tool": "name", "args": {...} } ``` or { "tool": "...", "args": {...} }
_TOOL_CALL_RE = re.compile(r"```(?:json)?\s*(\{\s*\"tool\".*?\})\s*```", re.DOTALL)


def extract_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract structured tool calls from agent LLM response."""
    calls: list[dict[str, Any]] = []
    # 1. Try markdown code block extraction
    for match in _TOOL_CALL_RE.finditer(text):
        try:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "tool" in data:
                calls.append(data)
        except json.JSONDecodeError:
            continue

    if calls:
        return calls

    # 2. Try raw JSON object search if no code blocks matched
    if '{"tool":' in text or '{"tool" :' in text:
        start = text.find('{"tool"')
        if start != -1:
            try:
                # Find matching closing brace
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
                if isinstance(data, dict) and "tool" in data:
                    calls.append(data)
            except json.JSONDecodeError:
                pass

    return calls


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

        try:
            while budget.steps < budget.max_steps:
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

                tool_calls = extract_tool_calls(response.text)
                if not tool_calls:
                    final_answer = response.text
                    break

                # Execute requested tools
                for tc in tool_calls:
                    budget.record_tool_call()
                    agent_run.tool_calls += 1
                    t_name = tc.get("tool", "")
                    t_args = tc.get("args", {})

                    t_start = time.perf_counter()
                    t_result = await self.registry.execute(t_name, t_args, context, capabilities)
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
                    content_str = (
                        f"TOOL RESULT ({t_name}):\n{t_result.output}"
                        if t_result.ok
                        else f"TOOL ERROR ({t_name}):\n{t_result.error}"
                    )
                    messages.append(LLMMessage(role="assistant", content=f"Executed tool {t_name}"))
                    messages.append(LLMMessage(role="user", content=content_str))

                await session.flush()

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
