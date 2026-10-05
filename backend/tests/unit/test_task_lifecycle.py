"""Regression tests for task lifecycle, concurrency protection, and retry mechanisms."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ConflictError, InvalidStateTransitionError
from app.models.enums import TaskStatus, TaskType
from app.models.task import Task, TaskEvent
from app.models.user import User
from app.orchestration.state_machine import can_transition, validate_transition
from app.services.task_service import TaskService


@pytest.mark.unit
def test_task_lifecycle_transitions() -> None:
    # 1. Active task statuses cannot transition backwards to PLANNING or CREATED
    for active in (
        TaskStatus.PLANNING,
        TaskStatus.ANALYZING,
        TaskStatus.INVESTIGATING,
        TaskStatus.APPLYING,
        TaskStatus.TESTING,
    ):
        assert can_transition(active, TaskStatus.CREATED) is False

    # 2. Completed task cannot transition to any active state
    assert can_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING) is False
    assert can_transition(TaskStatus.COMPLETED, TaskStatus.CREATED) is False
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING)

    # 3. Failed task can be retried: transitions to CREATED or PLANNING
    assert can_transition(TaskStatus.FAILED, TaskStatus.CREATED) is True
    assert can_transition(TaskStatus.FAILED, TaskStatus.PLANNING) is True

    # 4. Awaiting approval cannot jump to PLANNING directly (must follow approval gate)
    assert can_transition(TaskStatus.AWAITING_APPROVAL, TaskStatus.PLANNING) is False


@pytest.mark.unit
async def test_retry_failed_task_increments_iteration_and_resets_state() -> None:
    task_id = uuid.uuid4()
    mock_task = Task(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix null pointer exception",
        description="Fix the bug in auth service",
        type=TaskType.BUG,
        status=TaskStatus.FAILED,
        iteration=1,
        error={"reason": "Sandbox timeout during execution"},
        summary="Previous attempt summary",
    )
    mock_user = User(
        id=uuid.uuid4(),
        email="developer@example.com",
        display_name="developer",
    )

    mock_session = AsyncMock()
    # First execute: select task with_for_update
    task_result = MagicMock()
    task_result.scalar_one_or_none.return_value = mock_task

    # Second execute: select max(seq)
    seq_result = MagicMock()
    seq_result.scalar_one.return_value = 5

    mock_session.execute.side_effect = [task_result, seq_result]
    mock_session.refresh = AsyncMock()
    mock_session.add = MagicMock()

    service = TaskService(session=mock_session)
    updated_task = await service.retry_task(task_id, mock_user)

    # Verify same task instance (no duplicate task created)
    assert updated_task.id == task_id
    # Verify iteration incremented
    assert updated_task.iteration == 2
    # Verify status transitioned to PLANNING
    assert updated_task.status == TaskStatus.PLANNING
    # Verify error, summary, finished_at reset
    assert updated_task.error is None
    assert updated_task.summary is None
    assert updated_task.finished_at is None

    # Verify events added
    added_events = [call.args[0] for call in mock_session.add.call_args_list if isinstance(call.args[0], TaskEvent)]
    assert len(added_events) == 2
    retry_event = added_events[0]
    assert retry_event.event_type == "task_retried"
    assert retry_event.seq == 6
    assert retry_event.payload["iteration"] == 2
    assert retry_event.payload["previous_status"] == "FAILED"

    status_event = added_events[1]
    assert status_event.event_type == "status_change"
    assert status_event.seq == 7
    assert status_event.payload["new_status"] == "PLANNING"


@pytest.mark.unit
async def test_retry_on_non_failed_task_is_rejected() -> None:
    task_id = uuid.uuid4()
    for invalid_status in (TaskStatus.CREATED, TaskStatus.PLANNING, TaskStatus.ANALYZING, TaskStatus.COMPLETED):
        mock_task = Task(
            id=task_id,
            repository_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            title="Some task",
            type=TaskType.BUG,
            status=invalid_status,
            iteration=1,
        )
        mock_user = User(id=uuid.uuid4(), email="dev@example.com", display_name="dev")

        mock_session = AsyncMock()
        task_result = MagicMock()
        task_result.scalar_one_or_none.return_value = mock_task
        mock_session.execute.return_value = task_result

        service = TaskService(session=mock_session)
        with pytest.raises(ConflictError) as exc_info:
            await service.retry_task(task_id, mock_user)

        assert "Only FAILED tasks can be retried" in str(exc_info.value)


@pytest.mark.unit
async def test_run_task_concurrency_and_active_state_rejection() -> None:
    from app.api.routes.tasks import run_task

    user = User(id=uuid.uuid4(), email="user@example.com", display_name="user")

    # 1. Active task must reject run request
    for active_status in (
        TaskStatus.PLANNING,
        TaskStatus.ANALYZING,
        TaskStatus.INVESTIGATING,
        TaskStatus.APPLYING,
        TaskStatus.TESTING,
    ):
        mock_task = Task(
            id=uuid.uuid4(),
            repository_id=uuid.uuid4(),
            user_id=user.id,
            title="Active Task",
            type=TaskType.BUG,
            status=active_status,
        )
        db = AsyncMock()
        res = MagicMock()
        res.scalar_one_or_none.return_value = mock_task
        db.execute.return_value = res

        service = AsyncMock()

        with pytest.raises(ConflictError) as exc_info:
            await run_task(task_id=mock_task.id, current_user=user, service=service, db=db)

        assert "already has an active execution" in str(exc_info.value)

    # 2. Completed task cannot be re-run
    completed_task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=user.id,
        title="Completed Task",
        type=TaskType.BUG,
        status=TaskStatus.COMPLETED,
    )
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = completed_task
    db.execute.return_value = res

    with pytest.raises(ConflictError) as exc_info:
        await run_task(task_id=completed_task.id, current_user=user, service=AsyncMock(), db=db)

    assert "is completed and cannot be started again" in str(exc_info.value)

    # 3. Awaiting approval task cannot be re-run directly
    approval_task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=user.id,
        title="Awaiting Approval Task",
        type=TaskType.BUG,
        status=TaskStatus.AWAITING_APPROVAL,
    )
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = approval_task
    db.execute.return_value = res

    with pytest.raises(ConflictError) as exc_info:
        await run_task(task_id=approval_task.id, current_user=user, service=AsyncMock(), db=db)

    assert "awaiting human approval" in str(exc_info.value)

    # 4. Failed task cannot use run_task (must use retry)
    failed_task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=user.id,
        title="Failed Task",
        type=TaskType.BUG,
        status=TaskStatus.FAILED,
    )
    db = AsyncMock()
    res = MagicMock()
    res.scalar_one_or_none.return_value = failed_task
    db.execute.return_value = res

    with pytest.raises(ConflictError) as exc_info:
        await run_task(task_id=failed_task.id, current_user=user, service=AsyncMock(), db=db)

    assert "Use retry instead of start" in str(exc_info.value)


@pytest.mark.unit
async def test_created_task_start_agent_transitions_to_planning() -> None:
    from datetime import UTC, datetime

    from app.api.routes.tasks import run_task

    now = datetime.now(UTC)
    user = User(id=uuid.uuid4(), email="user@example.com", display_name="user")
    created_task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=user.id,
        title="Fresh Task",
        description="Objective",
        type=TaskType.BUG,
        status=TaskStatus.CREATED,
        iteration=1,
        total_prompt_tokens=0,
        total_completion_tokens=0,
        tool_call_count=0,
        sandbox_run_count=0,
        created_at=now,
        updated_at=now,
    )

    db = AsyncMock()
    db.add = MagicMock()
    task_res = MagicMock()
    task_res.scalar_one_or_none.return_value = created_task
    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 1
    db.execute.side_effect = [task_res, seq_res]
    db.refresh = AsyncMock()

    with patch("app.api.routes.tasks._enqueue_run_task_job", new_callable=AsyncMock) as mock_enqueue:
        res = await run_task(task_id=created_task.id, current_user=user, service=AsyncMock(), db=db)
        assert created_task.status == TaskStatus.PLANNING
        assert mock_enqueue.called
        assert res.status == TaskStatus.PLANNING


@pytest.mark.unit
async def test_retry_max_attempts_enforcement() -> None:
    from app.core.config import Settings

    task_id = uuid.uuid4()
    mock_task = Task(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Max retry task",
        type=TaskType.BUG,
        status=TaskStatus.FAILED,
        iteration=3,  # already at limit 3
    )
    mock_user = User(id=uuid.uuid4(), email="dev@example.com", display_name="dev")
    settings = Settings(max_fix_attempts=3)

    mock_session = AsyncMock()
    task_result = MagicMock()
    task_result.scalar_one_or_none.return_value = mock_task
    mock_session.execute.return_value = task_result

    service = TaskService(session=mock_session, settings=settings)
    with pytest.raises(ConflictError) as exc_info:
        await service.retry_task(task_id, mock_user)

    assert "reached the maximum allowed retry attempts" in str(exc_info.value)
