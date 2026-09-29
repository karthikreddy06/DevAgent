"""Task state machine transitions and validation."""

from __future__ import annotations

from app.core.errors import InvalidStateTransitionError
from app.models.enums import TaskStatus

# Permitted state transitions
ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.PLANNING, TaskStatus.FAILED, TaskStatus.REJECTED}),
    TaskStatus.PLANNING: frozenset({TaskStatus.ANALYZING, TaskStatus.FAILED, TaskStatus.REJECTED}),
    TaskStatus.ANALYZING: frozenset({TaskStatus.INVESTIGATING, TaskStatus.FAILED, TaskStatus.REJECTED}),
    TaskStatus.INVESTIGATING: frozenset(
        {TaskStatus.FIX_PROPOSED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.REJECTED}
    ),
    TaskStatus.FIX_PROPOSED: frozenset({TaskStatus.AWAITING_APPROVAL, TaskStatus.FAILED, TaskStatus.REJECTED}),
    TaskStatus.AWAITING_APPROVAL: frozenset(
        {TaskStatus.APPLYING, TaskStatus.REJECTED, TaskStatus.INVESTIGATING, TaskStatus.FAILED}
    ),
    TaskStatus.APPLYING: frozenset({TaskStatus.TESTING, TaskStatus.COMPLETED, TaskStatus.FAILED}),
    TaskStatus.TESTING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.INVESTIGATING, TaskStatus.FAILED, TaskStatus.AWAITING_APPROVAL}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.REJECTED: frozenset(),
}


def can_transition(current: TaskStatus, target: TaskStatus) -> bool:
    """Return True if transitioning from current to target is allowed."""
    if current == target:
        return True
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def validate_transition(current: TaskStatus, target: TaskStatus) -> None:
    """Raise InvalidStateTransitionError if the transition is prohibited."""
    if not can_transition(current, target):
        allowed = [s.value for s in ALLOWED_TRANSITIONS.get(current, frozenset())]
        raise InvalidStateTransitionError(
            f"Cannot transition task from {current.value} to {target.value}",
            details={"current_status": current.value, "target_status": target.value, "allowed_transitions": allowed},
        )
