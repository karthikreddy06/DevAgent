"""End-to-End DevAgent task execution test using real Docker sandbox.

Verifies complete lifecycle on the buggy-auth-service fixture:
CREATED -> PLANNING -> ANALYZING -> INVESTIGATING -> FIX_PROPOSED
-> AWAITING_APPROVAL -> APPLYING -> TESTING -> COMPLETED
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import PolicyViolationError
from app.models.change import Approval, ProposedChange
from app.models.enums import ApprovalDecision, ApprovalKind, ChangeStatus, TaskStatus, TaskType
from app.models.task import Task
from app.orchestration.state_machine import validate_transition
from app.tools import create_default_registry, permissions_for_status
from app.tools.base import ToolContext
from app.tools.docker.runner import DockerSandboxExecutor, docker_available
from app.tools.permissions import INVESTIGATION


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_end_to_end_buggy_fixture_lifecycle(tmp_path: Path) -> None:
    if not docker_available():
        pytest.skip("Docker daemon is not available")

    # 1. Setup isolated workspace inside managed workspaces_dir
    settings = Settings(env="test", workspaces_dir=tmp_path / "workspaces")
    ws = settings.workspaces_dir / f"e2e-task-{uuid.uuid4().hex[:8]}"
    fixture_dir = Path("fixtures/buggy-auth-service").resolve()
    if not fixture_dir.exists():
        fixture_dir = Path("../fixtures/buggy-auth-service").resolve()
    shutil.copytree(fixture_dir, ws)

    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        title="Fix role hierarchy check in AuthService",
        description="check_permission uses strict > instead of >= causing same-level checks to fail",
        status=TaskStatus.CREATED,
        type=TaskType.BUG,
    )

    registry = create_default_registry()
    sandbox = DockerSandboxExecutor(
        task_id=str(task.id),
        workspace=ws,
        settings=settings,
    )
    tool_ctx = ToolContext(
        task_id=task.id,
        agent="e2e-test",
        workspace=ws,
        settings=settings,
        sandbox=sandbox,
    )

    try:
        # Step 1: CREATED -> PLANNING
        validate_transition(task.status, TaskStatus.PLANNING)
        task.status = TaskStatus.PLANNING

        # Step 2: PLANNING -> ANALYZING
        validate_transition(task.status, TaskStatus.ANALYZING)
        task.status = TaskStatus.ANALYZING

        # Step 3: ANALYZING -> INVESTIGATING
        validate_transition(task.status, TaskStatus.INVESTIGATING)
        task.status = TaskStatus.INVESTIGATING

        # Run tests in sandbox to reproduce the bug
        initial_test = await registry.execute(
            "run_command",
            {"command": ["pytest", "-v"], "purpose": "Reproduce test failure in sandbox"},
            tool_ctx,
            INVESTIGATION,
        )
        assert not initial_test.ok
        assert initial_test.exit_code == 1

        # Locate the bug with read_file
        read_res = await registry.execute(
            "read_file",
            {"path": "src/auth.py", "start_line": 40, "end_line": 50},
            tool_ctx,
            INVESTIGATION,
        )
        assert read_res.ok
        assert "hierarchy.get(user_role, 0) > hierarchy.get(required_role, 0)" in read_res.output

        # Step 4: INVESTIGATING -> FIX_PROPOSED
        validate_transition(task.status, TaskStatus.FIX_PROPOSED)
        task.status = TaskStatus.FIX_PROPOSED

        proposal = ProposedChange(
            task_id=task.id,
            iteration=1,
            status=ChangeStatus.AWAITING_APPROVAL,
            summary="Use >= for permission hierarchy check",
            patch_unified="- return hierarchy.get(user_role, 0) > hierarchy.get(required_role, 0)\n+ return hierarchy.get(user_role, 0) >= hierarchy.get(required_role, 0)",
        )
        approval = Approval(
            task_id=task.id,
            proposed_change_id=proposal.id,
            kind=ApprovalKind.APPLY_CHANGES,
        )

        # Step 5: FIX_PROPOSED -> AWAITING_APPROVAL
        validate_transition(task.status, TaskStatus.AWAITING_APPROVAL)
        task.status = TaskStatus.AWAITING_APPROVAL
        tool_ctx.task_status = TaskStatus.AWAITING_APPROVAL

        # Verify no changes happen before approval (write is prohibited)
        awaiting_caps = permissions_for_status(TaskStatus.AWAITING_APPROVAL)
        with pytest.raises(PolicyViolationError):
            await registry.execute(
                "write_file",
                {"path": "src/auth.py", "content": "malicious overwrite"},
                tool_ctx,
                awaiting_caps,
            )

        # Step 6: Human Approval Gate
        approval.decision = ApprovalDecision.APPROVED
        proposal.status = ChangeStatus.APPROVED
        validate_transition(task.status, TaskStatus.APPLYING)
        task.status = TaskStatus.APPLYING
        tool_ctx.task_status = TaskStatus.APPLYING

        # Step 7: Apply patch in APPLYING state
        applying_caps = permissions_for_status(TaskStatus.APPLYING)
        patch_res = await registry.execute(
            "apply_patch",
            {
                "path": "src/auth.py",
                "old_str": "return hierarchy.get(user_role, 0) > hierarchy.get(required_role, 0)",
                "new_str": "return hierarchy.get(user_role, 0) >= hierarchy.get(required_role, 0)",
            },
            tool_ctx,
            applying_caps,
        )
        assert patch_res.ok

        # Step 8: APPLYING -> TESTING
        validate_transition(task.status, TaskStatus.TESTING)
        task.status = TaskStatus.TESTING
        tool_ctx.task_status = TaskStatus.TESTING

        # Run retest in sandbox
        retest = await registry.execute(
            "run_command",
            {"command": ["pytest", "-v"], "purpose": "Validate fix in sandbox"},
            tool_ctx,
            INVESTIGATION,
        )
        assert retest.ok
        assert retest.exit_code == 0
        assert "1 passed" in retest.output

        # Step 9: TESTING -> COMPLETED
        validate_transition(task.status, TaskStatus.COMPLETED)
        task.status = TaskStatus.COMPLETED
        assert task.status == TaskStatus.COMPLETED

    finally:
        await sandbox.destroy()
