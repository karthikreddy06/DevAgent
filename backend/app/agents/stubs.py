"""Stubs for future specialized agents (Security, Documentation, Git)."""

from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName
from app.models.task import Task


class SecurityAgent(BaseAgent):
    name = AgentName.SECURITY
    system_prompt = "You are the DevAgent Security Auditor (experimental)."

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        return f"Audit repository changes for security flaws: {task.title}"


class DocumentationAgent(BaseAgent):
    name = AgentName.DOCUMENTATION
    system_prompt = "You are the DevAgent Technical Writer."

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        return f"Generate or update documentation for: {task.title}"


class GitAgent(BaseAgent):
    name = AgentName.GIT
    system_prompt = "You are the DevAgent Git Coordinator."

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        return f"Manage git branch and PR operations for: {task.title}"
