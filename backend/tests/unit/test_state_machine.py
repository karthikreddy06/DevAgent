"""Unit tests for task state machine."""

from __future__ import annotations

import pytest

from app.core.errors import InvalidStateTransitionError
from app.models.enums import TaskStatus
from app.orchestration.state_machine import can_transition, validate_transition


@pytest.mark.unit
def test_valid_transitions() -> None:
    assert can_transition(TaskStatus.CREATED, TaskStatus.PLANNING) is True
    assert can_transition(TaskStatus.PLANNING, TaskStatus.ANALYZING) is True
    assert can_transition(TaskStatus.ANALYZING, TaskStatus.INVESTIGATING) is True
    assert can_transition(TaskStatus.INVESTIGATING, TaskStatus.FIX_PROPOSED) is True
    assert can_transition(TaskStatus.FIX_PROPOSED, TaskStatus.AWAITING_APPROVAL) is True
    assert can_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.APPLYING) is True
    assert can_transition(TaskStatus.APPLYING, TaskStatus.TESTING) is True
    assert can_transition(TaskStatus.TESTING, TaskStatus.COMPLETED) is True


@pytest.mark.unit
def test_invalid_transitions() -> None:
    # Cannot jump straight from CREATED to COMPLETED
    assert can_transition(TaskStatus.CREATED, TaskStatus.COMPLETED) is False
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskStatus.CREATED, TaskStatus.COMPLETED)

    # Completed tasks are terminal
    assert can_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING) is False
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING)
