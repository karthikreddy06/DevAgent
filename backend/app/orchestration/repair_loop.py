"""Iterative repair loop logic: hypothesis -> fix -> test -> feedback."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.models.enums import TaskStatus
from app.models.task import Task
from app.orchestration.state_machine import validate_transition

logger = get_logger(__name__)


@dataclass
class RepairLoopContext:
    iteration: int
    max_attempts: int
    last_failure_reason: str | None = None
    test_failures: list[str] | None = None

    @property
    def has_attempts_remaining(self) -> bool:
        return self.iteration < self.max_attempts


def prepare_repair_attempt(task: Task, max_attempts: int, failure_summary: str) -> bool:
    """Evaluate whether another fix attempt is allowed and transition task accordingly."""
    if task.iteration >= max_attempts:
        logger.warning("repair_loop_budget_exhausted", task_id=str(task.id), iteration=task.iteration)
        validate_transition(task.status, TaskStatus.FAILED)
        task.status = TaskStatus.FAILED
        task.error = {
            "reason": "Max fix attempts reached without passing tests",
            "last_failure": failure_summary,
            "attempts": task.iteration,
        }
        return False

    task.iteration += 1
    validate_transition(task.status, TaskStatus.INVESTIGATING)
    task.status = TaskStatus.INVESTIGATING
    logger.info("repair_loop_retry_scheduled", task_id=str(task.id), iteration=task.iteration)
    return True
