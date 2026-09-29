"""Worker job to apply approved changes and run sandbox verification tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.errors import PolicyViolationError, ValidationError
from app.core.paths import safe_join
from app.database.session import get_session_factory
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import ChangeStatus, EventLevel, TaskStatus
from app.models.task import Task, TaskEvent
from app.orchestration.state_machine import validate_transition
from app.services.repo_service import RepoService
from app.services.test_service import TestService
from app.tools.docker.runner import DockerSandboxExecutor

logger = get_logger(__name__)


async def apply_and_test_job(ctx: dict[str, Any], approval_id: str) -> bool:
    """Apply approved change to workspace, run sandbox tests, and finalize task status."""
    settings = get_settings()
    session_factory = get_session_factory()
    appr_uuid = uuid.UUID(approval_id)

    async with session_factory() as session:
        # Load approval and task
        appr_stmt = select(Approval).where(Approval.id == appr_uuid)
        appr_res = await session.execute(appr_stmt)
        approval = appr_res.scalar_one_or_none()
        if not approval:
            logger.error("apply_and_test_approval_not_found", approval_id=approval_id)
            return False

        task_stmt = select(Task).where(Task.id == approval.task_id)
        task_res = await session.execute(task_stmt)
        task = task_res.scalar_one()

        change = None
        if approval.proposed_change_id:
            c_stmt = select(ProposedChange).where(ProposedChange.id == approval.proposed_change_id)
            c_res = await session.execute(c_stmt)
            change = c_res.scalar_one_or_none()

        repo_service = RepoService(session, settings)
        workspace = repo_service.workspace_path(task.repository_id)

        seq_res = await session.execute(
            select(func.coalesce(func.max(TaskEvent.seq), 0)).where(TaskEvent.task_id == task.id)
        )
        cur_seq = seq_res.scalar_one()

        # 1. State: APPLYING
        validate_transition(task.status, TaskStatus.APPLYING)
        task.status = TaskStatus.APPLYING
        cur_seq += 1
        ev1 = TaskEvent(
            task_id=task.id,
            seq=cur_seq,
            event_type="approval_granted",
            level=EventLevel.INFO,
            message="Change approved, applying patch to workspace",
        )
        session.add(ev1)

        # Apply file changes
        if change:
            cf_stmt = select(ChangeFile).where(ChangeFile.proposed_change_id == change.id)
            cf_res = await session.execute(cf_stmt)
            change_files = cf_res.scalars().all()
            for cf in change_files:
                try:
                    target = safe_join(workspace, cf.path)
                except (ValidationError, PolicyViolationError) as exc:
                    logger.error("apply_patch_unsafe_path", path=cf.path, error=str(exc))
                    validate_transition(task.status, TaskStatus.FAILED)
                    task.status = TaskStatus.FAILED
                    task.error = {"reason": f"Unsafe file path in approved change: {cf.path}", "details": str(exc)}
                    cur_seq += 1
                    err_ev = TaskEvent(
                        task_id=task.id,
                        seq=cur_seq,
                        event_type="apply_patch_failed",
                        level=EventLevel.ERROR,
                        message=f"Path containment violation for {cf.path}: {exc}",
                    )
                    session.add(err_ev)
                    await session.commit()
                    return False

                if cf.proposed_content is not None:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(cf.proposed_content, encoding="utf-8")
                cf.applied = True
                cf.applied_at = datetime.now(UTC)

            change.status = ChangeStatus.APPLIED
            change.applied_at = datetime.now(UTC)

        # 2. State: TESTING
        validate_transition(task.status, TaskStatus.TESTING)
        task.status = TaskStatus.TESTING
        cur_seq += 1
        ev2 = TaskEvent(
            task_id=task.id,
            seq=cur_seq,
            event_type="testing_started",
            level=EventLevel.INFO,
            message="Running verification tests in isolated sandbox container",
        )
        session.add(ev2)
        await session.commit()

        # 3. Sandbox Retest
        sandbox = ctx.get("sandbox")
        cleanup_sandbox = False
        if sandbox is None and settings.sandbox_enabled:
            sandbox = DockerSandboxExecutor(task_id=str(task.id), workspace=workspace, settings=settings)
            await sandbox.start()
            cleanup_sandbox = True

        try:
            test_service = TestService(session, settings)
            test_run = await test_service.run_tests(task.id, ["pytest", "-v"], sandbox, phase="verification")

            cur_seq += 1
            if test_run.all_passed:
                validate_transition(task.status, TaskStatus.COMPLETED)
                task.status = TaskStatus.COMPLETED
                task.summary = f"All {test_run.passed} tests passed. Fix successfully verified in sandbox."
                ev3 = TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="task_completed",
                    level=EventLevel.INFO,
                    message=f"Task completed successfully: {test_run.summary}",
                )
                session.add(ev3)
                logger.info("apply_and_test_succeeded", task_id=str(task.id), summary=test_run.summary)
                await session.commit()
                return True
            else:
                validate_transition(task.status, TaskStatus.FAILED)
                task.status = TaskStatus.FAILED
                task.error = {
                    "reason": "Verification tests failed after applying patch",
                    "summary": test_run.summary,
                    "stdout": test_run.stdout_tail,
                }
                ev3 = TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="task_failed",
                    level=EventLevel.ERROR,
                    message=f"Verification tests failed: {test_run.summary}",
                )
                session.add(ev3)
                logger.warning("apply_and_test_failed", task_id=str(task.id), summary=test_run.summary)
                await session.commit()
                return False
        finally:
            if cleanup_sandbox and sandbox is not None:
                await sandbox.destroy()
