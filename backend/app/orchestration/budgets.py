"""Agent execution budgets and tracking."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import BudgetExhaustedError


@dataclass
class BudgetTracker:
    """Monitors token, step, tool-call, and time limits for a single agent execution."""

    max_steps: int = 12
    max_tool_calls: int = 24
    max_tokens: int = 120_000
    timeout_seconds: float = 900.0

    steps: int = 0
    tool_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    start_time: float = field(default_factory=time.perf_counter)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> BudgetTracker:
        s = settings or get_settings()
        return cls(
            max_steps=s.agent_max_steps,
            max_tool_calls=s.agent_max_tool_calls,
            max_tokens=s.agent_max_tokens,
            timeout_seconds=float(s.agent_timeout_seconds),
        )

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def elapsed_seconds(self) -> float:
        return time.perf_counter() - self.start_time

    def record_step(self) -> None:
        self.steps += 1
        self.check_limits()

    def record_tool_call(self) -> None:
        self.tool_calls += 1
        self.check_limits()

    def record_tokens(self, prompt: int, completion: int) -> None:
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.check_limits()

    def check_limits(self) -> None:
        if self.steps > self.max_steps:
            raise BudgetExhaustedError(
                f"Agent step budget exhausted: {self.steps} > {self.max_steps}",
                details={"metric": "steps", "value": self.steps, "limit": self.max_steps},
            )
        if self.tool_calls > self.max_tool_calls:
            raise BudgetExhaustedError(
                f"Agent tool call budget exhausted: {self.tool_calls} > {self.max_tool_calls}",
                details={"metric": "tool_calls", "value": self.tool_calls, "limit": self.max_tool_calls},
            )
        if self.total_tokens > self.max_tokens:
            raise BudgetExhaustedError(
                f"Agent token budget exhausted: {self.total_tokens} > {self.max_tokens}",
                details={"metric": "tokens", "value": self.total_tokens, "limit": self.max_tokens},
            )
        if self.elapsed_seconds > self.timeout_seconds:
            raise BudgetExhaustedError(
                f"Agent execution timed out after {self.elapsed_seconds:.1f}s > {self.timeout_seconds}s",
                details={"metric": "timeout_seconds", "value": self.elapsed_seconds, "limit": self.timeout_seconds},
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "max_steps": self.max_steps,
            "tool_calls": self.tool_calls,
            "max_tool_calls": self.max_tool_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "timeout_seconds": self.timeout_seconds,
        }
