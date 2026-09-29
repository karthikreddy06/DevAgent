"""Tester agent: test execution, bug reproduction, and patch validation."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class TesterAgent(BaseAgent):
    name = AgentName.TESTER
    system_prompt = (
        "You are the DevAgent QA Engineer. Your job is to run relevant tests (using run_command), "
        "verify that existing tests fail before the fix or pass after the fix, and ensure no regressions occurred.\n"
        "Summarize test outcomes cleanly (passed, failed, skipped)."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        changes = extra_context.get("changes", "") if extra_context else ""
        return (
            f"TASK: {task.title}\n"
            f"DESCRIPTION: {task.description}\n"
            f"CHANGES APPLIED:\n{changes}\n\n"
            "Run the relevant test suite using `run_command` (e.g. ['pytest', '-v'] or specific test files). "
            "Report the exit code and whether all tests passed."
        )
