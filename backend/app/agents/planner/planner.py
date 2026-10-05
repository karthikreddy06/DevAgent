"""Planner agent: analyzes tasks and formulates step-by-step strategy."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class PlannerAgent(BaseAgent):
    name = AgentName.PLANNER
    system_prompt = (
        "You are the DevAgent Lead Planner. Your goal is to inspect the user's task and the repository layout, "
        "formulate a concrete investigation plan, and identify which files and test cases should be examined.\n"
        "Be concise, analytical, and structured."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        ctx_parts: list[str] = []
        if extra_context:
            pf = extra_context.get("previous_failure")
            if pf:
                ctx_parts.append(
                    f"PREVIOUS ATTEMPT FAILURE / ERROR:\n{pf}\nNOTE: Avoid repeating the previous failed approach."
                )
            rag = extra_context.get("rag_context")
            if rag:
                ctx_parts.append(f"RELEVANT CODE CONTEXT:\n{rag}")
        ctx_info = ("\n\n" + "\n\n".join(ctx_parts)) if ctx_parts else ""
        return (
            f"TASK TITLE: {task.title}\n"
            f"TASK TYPE: {task.type.value}\n"
            f"TASK DESCRIPTION:\n{task.description}{ctx_info}\n\n"
            "Please explore the repository using tools (e.g. list_files, search_codebase), "
            "then provide a concise plan of action listing:\n"
            "1. Likely root cause location / key files\n"
            "2. Investigation steps\n"
            "3. Verification criteria"
        )
