"""Codebase agent: semantic navigation and context gathering."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class CodebaseAgent(BaseAgent):
    name = AgentName.CODEBASE
    system_prompt = (
        "You are the DevAgent Codebase Specialist. Your goal is to pinpoint exact code snippets, "
        "function definitions, call hierarchies, and dependencies relevant to the task.\n"
        "Use search_codebase, find_symbol, read_file, and search_in_files."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        plan_info = extra_context.get("plan", "") if extra_context else ""
        prev_fail = extra_context.get("previous_failure", "") if extra_context else ""
        fail_section = (
            f"PREVIOUS ATTEMPT FAILURE / ERROR:\n{prev_fail}\n"
            "NOTE: Avoid investigating files or paths that led to the previous failure.\n\n"
            if prev_fail
            else ""
        )
        return (
            f"TASK: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"{fail_section}"
            f"PLAN SUGGESTION:\n{plan_info}\n\n"
            "Search and inspect the codebase. Identify the exact files, functions, and lines that need attention."
        )
