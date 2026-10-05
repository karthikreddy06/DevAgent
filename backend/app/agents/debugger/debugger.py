"""Debugger agent: fault localization and fix hypothesis generation."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class DebuggerAgent(BaseAgent):
    name = AgentName.DEBUGGER
    system_prompt = (
        "You are the DevAgent Senior Debugger. Your job is to locate the root cause of the problem, "
        "verify the defect with concrete repository evidence or reproduction, and formulate the minimal, correct fix.\n"
        "A speculative root-cause explanation alone is NOT sufficient. If you cannot establish a concrete, "
        "reproducible defect from repository evidence, do NOT propose a patch.\n"
        "When a concrete defect is confirmed, propose the exact fix using the propose_patch tool, providing "
        "the concrete evidence and the exact code replacement."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        code_context = extra_context.get("code_context", "") if extra_context else ""
        test_failures = extra_context.get("test_failures", "") if extra_context else ""
        previous_failure = extra_context.get("previous_failure", "") if extra_context else ""
        prev_fail_str = (
            f"PREVIOUS ATTEMPT FAILURE / ERROR:\n{previous_failure}\n"
            "NOTE: Do NOT repeat the previous failed hypothesis or approach. Formulate a verified solution.\n\n"
            if previous_failure
            else ""
        )
        return (
            f"TASK: {task.title}\n"
            f"DETAILS: {task.description}\n"
            f"{prev_fail_str}"
            f"CODE CONTEXT GATHERED:\n{code_context}\n"
            f"FAILURES / ERRORS:\n{test_failures}\n\n"
            "Analyze the bug, hypothesize the root cause, and implement or specify the fix."
        )
