"""Debugger agent: fault localization and fix hypothesis generation."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class DebuggerAgent(BaseAgent):
    name = AgentName.DEBUGGER
    system_prompt = (
        "You are the DevAgent Senior Debugger. Your job is to locate the root cause of the problem and "
        "formulate the minimal, correct fix.\n"
        "When formulating the fix, you MUST propose the exact patch using the propose_patch tool, or provide a "
        "```diff block with exact - <old> and + <new> lines so that human review and approval can be requested."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        code_context = extra_context.get("code_context", "") if extra_context else ""
        test_failures = extra_context.get("test_failures", "") if extra_context else ""
        return (
            f"TASK: {task.title}\n"
            f"DETAILS: {task.description}\n"
            f"CODE CONTEXT GATHERED:\n{code_context}\n"
            f"FAILURES / ERRORS:\n{test_failures}\n\n"
            "Analyze the bug, hypothesize the root cause, and implement or specify the fix."
        )
