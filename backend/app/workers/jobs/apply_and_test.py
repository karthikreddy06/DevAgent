"""Worker job to apply approved changes and run sandbox verification tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.errors import PolicyViolationError, ValidationError
from app.core.logging import get_logger
from app.core.paths import safe_join
from app.database.session import get_session_factory
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import ChangeStatus, EventLevel, TaskStatus
from app.models.task import Task, TaskEvent
from app.orchestration.state_machine import validate_transition
from app.services.repo_service import RepoService
from app.services.test_service import TestService
from app.tools.base import SandboxExecutor
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
        if not change:
            logger.error("apply_and_test_missing_change", approval_id=approval_id)
            validate_transition(task.status, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
            task.error = {"reason": "No file changes were applied; verification was not started."}
            cur_seq += 1
            session.add(
                TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="apply_patch_failed",
                    level=EventLevel.ERROR,
                    message="No file changes were applied; verification was not started.",
                )
            )
            await session.commit()
            return False

        cf_stmt = select(ChangeFile).where(ChangeFile.proposed_change_id == change.id)
        cf_res = await session.execute(cf_stmt)
        change_files = cf_res.scalars().all()

        if not change_files:
            logger.error("apply_and_test_no_change_files", change_id=str(change.id))
            validate_transition(task.status, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
            task.error = {"reason": "No file changes were applied; verification was not started."}
            cur_seq += 1
            session.add(
                TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="apply_patch_failed",
                    level=EventLevel.ERROR,
                    message="No file changes were applied; verification was not started.",
                )
            )
            await session.commit()
            return False

        applied_count = 0
        for cf in change_files:
            try:
                target = safe_join(workspace, cf.path)
            except (ValidationError, PolicyViolationError) as exc:
                logger.error("apply_patch_unsafe_path", path=cf.path, error=str(exc))
                validate_transition(task.status, TaskStatus.FAILED)
                task.status = TaskStatus.FAILED
                task.error = {"reason": f"Unsafe file path in approved change: {cf.path}", "details": str(exc)}
                cur_seq += 1
                session.add(
                    TaskEvent(
                        task_id=task.id,
                        seq=cur_seq,
                        event_type="apply_patch_failed",
                        level=EventLevel.ERROR,
                        message=f"Path containment violation for {cf.path}: {exc}",
                    )
                )
                await session.commit()
                return False

            if cf.proposed_content is not None:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(cf.proposed_content, encoding="utf-8")
                applied_count += 1
            cf.applied = True
            cf.applied_at = datetime.now(UTC)

        if applied_count < 1:
            logger.error("apply_and_test_zero_files_applied", change_id=str(change.id))
            validate_transition(task.status, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
            task.error = {"reason": "No file changes were applied; verification was not started."}
            cur_seq += 1
            session.add(
                TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="apply_patch_failed",
                    level=EventLevel.ERROR,
                    message="No file changes were applied; verification was not started.",
                )
            )
            await session.commit()
            return False

        change.status = ChangeStatus.APPLIED
        change.applied_at = datetime.now(UTC)

        # 2. State: TESTING (only reached when applied_count >= 1)
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

        # 3. Sandbox Retest with Smart Test Selection
        sandbox = ctx.get("sandbox")
        cleanup_sandbox = False
        if sandbox is None and settings.sandbox_enabled:
            sandbox = DockerSandboxExecutor(task_id=str(task.id), workspace=workspace, settings=settings)
            await sandbox.start()
            cleanup_sandbox = True

        # Determine smart test command:
        # 1. Custom test command from task.plan if provided by user
        # 2. Targeted test discovery based on changed files
        # 3. Fallback to full ["pytest", "-v"]
        test_cmd = ["pytest", "-v"]
        user_test_cmd = None
        if task.plan and isinstance(task.plan, dict):
            user_test_cmd = task.plan.get("test_command")

        if user_test_cmd:
            import shlex

            parsed = shlex.split(user_test_cmd)
            if parsed and (parsed[0] == "pytest" or parsed[0].endswith("pytest")):
                test_cmd = parsed
            else:
                test_cmd = ["pytest", "-v"]
        else:
            changed_paths = [cf.path for cf in (change_files or [])]
            relevant_tests = []
            for cp in changed_paths:
                stem = Path(cp).stem
                candidates = [
                    workspace / f"tests/test_{stem}.py",
                    workspace / f"tests/{stem}_test.py",
                    workspace / f"test_{stem}.py",
                ]
                for cand in candidates:
                    if cand.is_file():
                        rel = cand.relative_to(workspace).as_posix()
                        if rel not in relevant_tests:
                            relevant_tests.append(rel)
            if relevant_tests:
                test_cmd = ["pytest", "-v", *relevant_tests]

        try:
            test_service = TestService(session, settings)
            test_run = await test_service.run_tests(
                task.id, test_cmd, cast(SandboxExecutor, sandbox), phase="verification"
            )

            cur_seq += 1
            if test_run.all_passed:
                validate_transition(task.status, TaskStatus.COMPLETED)
                task.status = TaskStatus.COMPLETED

                # Safe local Git operations: stage to task-specific branch without pushing
                git_branch = f"devagent/task-{str(task.id)[:8]}"
                git_info = None
                try:
                    import subprocess

                    if (workspace / ".git").is_dir():
                        subprocess.run(
                            ["git", "checkout", "-B", git_branch],
                            cwd=str(workspace),
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        subprocess.run(
                            ["git", "add", "."], cwd=str(workspace), capture_output=True, text=True, check=False
                        )
                        diff_res = subprocess.run(
                            ["git", "diff", "--staged", "--stat"],
                            cwd=str(workspace),
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        git_info = {
                            "branch": git_branch,
                            "status": "commit_ready",
                            "staged_diff": diff_res.stdout.strip(),
                            "suggested_commit": f"fix: {task.title}",
                        }
                        from app.models.enums import GitOperationKind, GitOperationStatus
                        from app.models.git import GitOperation

                        git_op = GitOperation(
                            repository_id=task.repository_id,
                            task_id=task.id,
                            kind=GitOperationKind.BRANCH,
                            status=GitOperationStatus.SUCCEEDED,
                            branch=git_branch,
                            detail=git_info,
                        )
                        session.add(git_op)
                        cur_seq += 1
                        branch_ev = TaskEvent(
                            task_id=task.id,
                            seq=cur_seq,
                            event_type="git_branch_ready",
                            level=EventLevel.INFO,
                            message=f"Changes staged on local branch '{git_branch}'. Ready for commit.",
                            payload=git_info,
                        )
                        session.add(branch_ev)
                except Exception as g_err:
                    logger.warning("git_branch_setup_failed", error=str(g_err))

                current_plan = dict(task.plan) if (task.plan and isinstance(task.plan, dict)) else {}
                if git_info:
                    current_plan["git"] = git_info
                task.plan = current_plan

                branch_suffix = f" Branch '{git_branch}' is commit-ready." if git_info else ""
                task.summary = f"FIXED_AND_VERIFIED: All {test_run.passed} tests passed. Fix successfully verified in sandbox.{branch_suffix}"
                cur_seq += 1
                ev3 = TaskEvent(
                    task_id=task.id,
                    seq=cur_seq,
                    event_type="task_completed",
                    level=EventLevel.INFO,
                    message=f"Task completed successfully: {test_run.summary}",
                    payload={"git": git_info} if git_info else None,
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
