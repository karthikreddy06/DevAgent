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
        ctx_info = f"\nExtra context: {extra_context}" if extra_context else ""
        return (
            f"TASK TITLE: {task.title}\n"
            f"TASK TYPE: {task.type.value}\n"
            f"TASK DESCRIPTION:\n{task.description}\n{ctx_info}\n\n"
            "Please explore the repository using tools (e.g. list_files, search_codebase), "
            "then provide a concise plan of action listing:\n"
            "1. Likely root cause location / key files\n"
            "2. Investigation steps\n"
            "3. Verification criteria"
        )
