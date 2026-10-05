"""Comprehensive regression tests for Phase 1 Safety and Correctness Invariants.

Verifies:
A. No confirmed bug -> NO_CONFIRMED_BUG terminal outcome, no patch, no approval, no changes, no applying/testing.
B. Speculative regex output -> verify free-form +/- or 'to:' text never synthesizes a patch.
C. Invalid proposal -> pre-approval validation fails, task goes directly to FAILED, never enters FIX_PROPOSED.
D. Valid proposal -> validated first, ProposedChange + ChangeFiles persisted, then FIX_PROPOSED, then AWAITING_APPROVAL.
E. Invalid approval -> approval with missing/invalid proposed_change cannot enter APPLYING.
F. No actual file application -> apply_and_test fails when applied_count < 1, never enters TESTING.
G. Successful repair -> valid approved patch is applied, enters TESTING, tests pass, reaches COMPLETED with FIXED_AND_VERIFIED.
H. Existing rejection path -> rejecting proposal results in REJECTED, no patch applied, no tests executed.
"""

from __future__ import annotations

import difflib
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import (
    ApprovalDecision,
    ApprovalKind,
    ChangeStatus,
    ChangeType,
    TaskStatus,
    TaskType,
)
from app.models.task import Task
from app.models.user import User
from app.orchestration.orchestrator import TaskOrchestrator, extract_or_build_proposal
from app.services.change_service import ChangeService
from app.tools.base import ToolContext
from app.tools.registry import ToolRegistry
from app.workers.jobs.apply_and_test import apply_and_test_job


# ---------------------------------------------------------------------------
# Test A: No Confirmed Bug
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_no_confirmed_bug_outcome(temp_workspace: Path, test_settings: Settings) -> None:
    calc_file = temp_workspace / "src" / "calculator.py"
    original_code = calc_file.read_text(encoding="utf-8")

    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Check possible arithmetic issue",
        description="User suspects calculator add might fail for negative numbers",
        type=TaskType.BUG,
        status=TaskStatus.CREATED,
        iteration=1,
    )

    mock_session = AsyncMock()
    mock_session.new = set()
    added_objects = []

    def fake_add(obj):
        added_objects.append(obj)
        mock_session.new.add(obj)

    mock_session.add = MagicMock(side_effect=fake_add)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 0
    mock_session.execute.return_value = seq_res

    mock_llm = AsyncMock()
    mock_registry = ToolRegistry()

    orchestrator = TaskOrchestrator(
        session=mock_session,
        llm=mock_llm,
        registry=mock_registry,
        settings=test_settings,
    )

    hypothesis_text = (
        "Root cause analysis: I investigated the addition function. "
        "All arithmetic conforms to Python language specifications. "
        "No reproducible bug was observed in the test suite or repository."
    )

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", new_callable=AsyncMock) as mock_debug,
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan: inspect calculator"
        mock_code.return_value = "Code analysis: calculator functions are simple"
        mock_debug.return_value = hypothesis_text
        mock_rag.return_value = ([], "rag context")

        terminal_status = await orchestrator.execute_task(task, temp_workspace)

    # Invariant 1: No confirmed bug -> NO patch, task finishes as COMPLETED with NO_CONFIRMED_BUG
    assert terminal_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert "NO_CONFIRMED_BUG" in (task.summary or "")
    assert task.root_cause is not None
    assert task.root_cause.get("outcome") == "NO_CONFIRMED_BUG"

    # Invariant: No ProposedChange, No Approval, No ChangeFile persisted
    proposed_changes = [o for o in added_objects if isinstance(o, ProposedChange)]
    approvals = [o for o in added_objects if isinstance(o, Approval)]
    change_files = [o for o in added_objects if isinstance(o, ChangeFile)]
    assert len(proposed_changes) == 0
    assert len(approvals) == 0
    assert len(change_files) == 0

    # Invariant 9: No files in workspace were modified
    assert calc_file.read_text(encoding="utf-8") == original_code


# ---------------------------------------------------------------------------
# Test B: Speculative Regex Fallback is Disabled
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_speculative_regex_output_rejected(temp_workspace: Path, test_settings: Settings) -> None:
    tool_ctx = ToolContext(
        task_id=uuid.uuid4(),
        agent="debugger",  # type: ignore[arg-type]
        workspace=temp_workspace,
        settings=test_settings,
    )

    # 1. Speculative diff block with +/- lines in free-form LLM text
    speculative_text_1 = """
    I think the bug is in calculator.py:
    - return a + b
    + return a * b
    This should fix everything.
    """
    res1 = extract_or_build_proposal(tool_ctx, speculative_text_1, temp_workspace)
    assert res1 is None

    # 2. Speculative `<old> to: <new>` pattern
    speculative_text_2 = """
    We need to change:
    return a + b
    to:
    return a + b + 1
    """
    res2 = extract_or_build_proposal(tool_ctx, speculative_text_2, temp_workspace)
    assert res2 is None

    # 3. Arbitrary diff code block without structured tool invocation
    speculative_text_3 = """
    ```diff
    --- a/src/calculator.py
    +++ b/src/calculator.py
    @@ -2,3 +2,3 @@
    -    return a + b
    +    return a * b
    ```
    """
    res3 = extract_or_build_proposal(tool_ctx, speculative_text_3, temp_workspace)
    assert res3 is None


# ---------------------------------------------------------------------------
# Test C: Invalid Proposal Rejects Before FIX_PROPOSED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_invalid_proposal_cannot_enter_fix_proposed(temp_workspace: Path, test_settings: Settings) -> None:
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix syntax issue",
        type=TaskType.BUG,
        status=TaskStatus.CREATED,
        iteration=1,
    )

    mock_session = AsyncMock()
    mock_session.new = set()
    added_objects = []

    def fake_add(obj):
        added_objects.append(obj)
        mock_session.new.add(obj)

    mock_session.add = MagicMock(side_effect=fake_add)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 0
    mock_session.execute.return_value = seq_res

    mock_llm = AsyncMock()
    mock_registry = ToolRegistry()
    orchestrator = TaskOrchestrator(
        session=mock_session,
        llm=mock_llm,
        registry=mock_registry,
        settings=test_settings,
    )

    # Propose patch with syntax error
    calc_path = "src/calculator.py"
    invalid_patch = {
        "path": calc_path,
        "old_str": "return a + b",
        "new_str": "return a + ((",  # Syntax error
        "explanation": "Broken syntax",
        "evidence": "Observed crash",
        "unified_diff": "dummy diff",
        "original_content": "def add(a, b):\n    return a + b\n",
        "proposed_content": "def add(a, b):\n    return a + ((\n",
        "change_type": "modify",
    }

    async def fake_debugger_run(t, ctx, *args, **kwargs):
        ctx.proposed_patch = invalid_patch
        ctx.proposed_patches = [invalid_patch]
        return "Formulated fix with syntax error"

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", side_effect=fake_debugger_run),
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan"
        mock_code.return_value = "Analysis"
        mock_rag.return_value = ([], "")

        status = await orchestrator.execute_task(task, temp_workspace)

    # Invariant 2 & 3: Invalid patch -> cannot enter FIX_PROPOSED; transitions to FAILED
    assert status == TaskStatus.FAILED
    assert task.status == TaskStatus.FAILED
    assert "pre-approval validation" in (task.error or {}).get("reason", "")

    # Invariant: No ProposedChange or Approval persisted
    assert not any(isinstance(o, ProposedChange) for o in added_objects)
    assert not any(isinstance(o, Approval) for o in added_objects)


# ---------------------------------------------------------------------------
# Test D: Valid Proposal Persists and Enters FIX_PROPOSED then AWAITING_APPROVAL
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_valid_proposal_reaches_fix_proposed_and_awaiting_approval(
    temp_workspace: Path, test_settings: Settings
) -> None:
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Add type hints comment",
        type=TaskType.BUG,
        status=TaskStatus.CREATED,
        iteration=1,
    )

    mock_session = AsyncMock()
    mock_session.new = set()
    added_objects = []

    def fake_add(obj):
        added_objects.append(obj)
        mock_session.new.add(obj)

    mock_session.add = MagicMock(side_effect=fake_add)
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 0
    mock_session.execute.return_value = seq_res

    mock_llm = AsyncMock()
    mock_registry = ToolRegistry()
    orchestrator = TaskOrchestrator(
        session=mock_session,
        llm=mock_llm,
        registry=mock_registry,
        settings=test_settings,
    )

    calc = temp_workspace / "src" / "calculator.py"
    calc_content = calc.read_text(encoding="utf-8")
    old_str = "return a + b"
    new_str = "return a + b  # optimized"
    diff = "".join(
        difflib.unified_diff(
            calc_content.splitlines(keepends=True),
            calc_content.replace(old_str, new_str).splitlines(keepends=True),
            fromfile="a/src/calculator.py",
            tofile="b/src/calculator.py",
        )
    )

    valid_patch = {
        "path": "src/calculator.py",
        "old_str": old_str,
        "new_str": new_str,
        "explanation": "Add optimized note",
        "evidence": "Verification test reproduction passed",
        "unified_diff": diff,
        "original_content": calc_content,
        "proposed_content": calc_content.replace(old_str, new_str),
        "change_type": "modify",
    }

    async def fake_debugger_run(t, ctx, *args, **kwargs):
        ctx.proposed_patch = valid_patch
        ctx.proposed_patches = [valid_patch]
        return "Formulated valid patch"

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", side_effect=fake_debugger_run),
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan"
        mock_code.return_value = "Analysis"
        mock_rag.return_value = ([], "")

        status = await orchestrator.execute_task(task, temp_workspace)

    # Invariant: Reached AWAITING_APPROVAL
    assert status == TaskStatus.AWAITING_APPROVAL
    assert task.status == TaskStatus.AWAITING_APPROVAL

    # ProposedChange and Approval persisted
    proposals = [o for o in added_objects if isinstance(o, ProposedChange)]
    approvals = [o for o in added_objects if isinstance(o, Approval)]
    change_files = [o for o in added_objects if isinstance(o, ChangeFile)]

    assert len(proposals) == 1
    assert len(approvals) == 1
    assert len(change_files) == 1
    assert proposals[0].patch_unified == diff
    assert approvals[0].proposed_change_id == proposals[0].id


# ---------------------------------------------------------------------------
# Test E: Invalid Approval Cannot Enter APPLYING
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_invalid_approval_cannot_enter_applying() -> None:
    user = User(id=uuid.uuid4(), email="lead@example.com", display_name="lead")
    task_id = uuid.uuid4()
    mock_task = Task(
        id=task_id, repository_id=uuid.uuid4(), user_id=user.id, title="Test", status=TaskStatus.AWAITING_APPROVAL
    )

    # 1. Approval with no proposed_change_id
    mock_approval_1 = Approval(
        id=uuid.uuid4(),
        task_id=task_id,
        proposed_change_id=None,
        kind=ApprovalKind.APPLY_CHANGES,
    )
    session_1 = AsyncMock()
    appr_res_1 = MagicMock()
    appr_res_1.scalar_one_or_none.return_value = mock_approval_1
    session_1.execute.return_value = appr_res_1

    service_1 = ChangeService(session_1)
    with pytest.raises(ValidationError) as exc1:
        await service_1.decide_approval(mock_approval_1.id, ApprovalDecision.APPROVED, user)
    assert "no associated proposed_change_id" in str(exc1.value)
    assert mock_task.status == TaskStatus.AWAITING_APPROVAL

    # 2. Approval with non-existent proposed change
    mock_approval_2 = Approval(
        id=uuid.uuid4(),
        task_id=task_id,
        proposed_change_id=uuid.uuid4(),
        kind=ApprovalKind.APPLY_CHANGES,
    )
    session_2 = AsyncMock()
    appr_res_2 = MagicMock()
    appr_res_2.scalar_one_or_none.return_value = mock_approval_2
    change_res_2 = MagicMock()
    change_res_2.scalar_one_or_none.return_value = None
    session_2.execute.side_effect = [appr_res_2, change_res_2]

    service_2 = ChangeService(session_2)
    with pytest.raises(NotFoundError):
        await service_2.decide_approval(mock_approval_2.id, ApprovalDecision.APPROVED, user)
    assert mock_task.status == TaskStatus.AWAITING_APPROVAL

    # 3. ProposedChange with empty patch
    change_id_3 = uuid.uuid4()
    mock_approval_3 = Approval(
        id=uuid.uuid4(),
        task_id=task_id,
        proposed_change_id=change_id_3,
        kind=ApprovalKind.APPLY_CHANGES,
    )
    mock_change_3 = ProposedChange(id=change_id_3, task_id=task_id, summary="Empty diff", patch_unified="")
    session_3 = AsyncMock()
    appr_res_3 = MagicMock()
    appr_res_3.scalar_one_or_none.return_value = mock_approval_3
    change_res_3 = MagicMock()
    change_res_3.scalar_one_or_none.return_value = mock_change_3
    session_3.execute.side_effect = [appr_res_3, change_res_3]

    service_3 = ChangeService(session_3)
    with pytest.raises(ValidationError) as exc3:
        await service_3.decide_approval(mock_approval_3.id, ApprovalDecision.APPROVED, user)
    assert "contains no valid unified diff patch" in str(exc3.value)
    assert mock_task.status == TaskStatus.AWAITING_APPROVAL


# ---------------------------------------------------------------------------
# Test F: No Actual File Application Fails and Cannot Enter TESTING
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_apply_and_test_requires_applied_files(temp_workspace: Path) -> None:
    task_id = uuid.uuid4()
    change_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    mock_task = Task(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Test Task",
        status=TaskStatus.APPLYING,
    )
    mock_approval = Approval(
        id=approval_id,
        task_id=task_id,
        proposed_change_id=change_id,
        kind=ApprovalKind.APPLY_CHANGES,
        decision=ApprovalDecision.APPROVED,
    )
    mock_change = ProposedChange(
        id=change_id,
        task_id=task_id,
        summary="Test change",
        patch_unified="diff --git a/src/test.py b/src/test.py",
        status=ChangeStatus.APPROVED,
    )
    # ChangeFile with proposed_content = None (cannot write anything)
    mock_cf = ChangeFile(
        id=uuid.uuid4(),
        proposed_change_id=change_id,
        task_id=task_id,
        path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        proposed_content=None,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    appr_res = MagicMock()
    appr_res.scalar_one_or_none.return_value = mock_approval

    task_res = MagicMock()
    task_res.scalar_one.return_value = mock_task

    change_res = MagicMock()
    change_res.scalar_one_or_none.return_value = mock_change

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 1

    cf_res = MagicMock()
    cf_res.scalars.return_value.all.return_value = [mock_cf]

    mock_session.execute.side_effect = [appr_res, task_res, change_res, seq_res, cf_res]

    fake_session_factory = MagicMock()
    fake_session_factory.return_value.__aenter__.return_value = mock_session

    with (
        patch("app.workers.jobs.apply_and_test.get_session_factory", return_value=fake_session_factory),
        patch("app.workers.jobs.apply_and_test.RepoService.workspace_path", return_value=temp_workspace),
        patch("app.workers.jobs.apply_and_test.TestService.run_tests", new_callable=AsyncMock) as mock_run_tests,
    ):
        ok = await apply_and_test_job({}, str(approval_id))

    # Invariant 5 & 6: applied_count < 1 -> execution fails, NEVER enters TESTING
    assert ok is False
    assert mock_task.status == TaskStatus.FAILED
    assert "No file changes were applied" in (mock_task.error or {}).get("reason", "")
    assert not mock_run_tests.called


# ---------------------------------------------------------------------------
# Test G: Successful Repair Lifecycle Reaches COMPLETED with FIXED_AND_VERIFIED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_successful_repair_completes_with_verified_summary(temp_workspace: Path) -> None:
    task_id = uuid.uuid4()
    change_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    mock_task = Task(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix Addition Logic",
        status=TaskStatus.APPLYING,
    )
    mock_approval = Approval(
        id=approval_id,
        task_id=task_id,
        proposed_change_id=change_id,
        kind=ApprovalKind.APPLY_CHANGES,
        decision=ApprovalDecision.APPROVED,
    )
    mock_change = ProposedChange(
        id=change_id,
        task_id=task_id,
        summary="Valid Fix",
        patch_unified="diff --git a/src/calculator.py b/src/calculator.py",
        status=ChangeStatus.APPROVED,
    )
    new_content = "def add(a: int, b: int) -> int:\n    return a + b  # fixed\n"
    mock_cf = ChangeFile(
        id=uuid.uuid4(),
        proposed_change_id=change_id,
        task_id=task_id,
        path="src/calculator.py",
        change_type=ChangeType.MODIFY,
        proposed_content=new_content,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    appr_res = MagicMock()
    appr_res.scalar_one_or_none.return_value = mock_approval

    task_res = MagicMock()
    task_res.scalar_one.return_value = mock_task

    change_res = MagicMock()
    change_res.scalar_one_or_none.return_value = mock_change

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 1

    cf_res = MagicMock()
    cf_res.scalars.return_value.all.return_value = [mock_cf]

    mock_session.execute.side_effect = [appr_res, task_res, change_res, seq_res, cf_res]

    fake_session_factory = MagicMock()
    fake_session_factory.return_value.__aenter__.return_value = mock_session

    mock_test_run = MagicMock()
    mock_test_run.all_passed = True
    mock_test_run.passed = 5
    mock_test_run.summary = "5 passed in 0.12s"

    mock_sandbox = AsyncMock()
    with (
        patch("app.workers.jobs.apply_and_test.get_session_factory", return_value=fake_session_factory),
        patch("app.workers.jobs.apply_and_test.RepoService.workspace_path", return_value=temp_workspace),
        patch(
            "app.workers.jobs.apply_and_test.TestService.run_tests", new_callable=AsyncMock, return_value=mock_test_run
        ),
    ):
        ok = await apply_and_test_job({"sandbox": mock_sandbox}, str(approval_id))

    assert ok is True
    assert mock_task.status == TaskStatus.COMPLETED
    assert mock_task.summary is not None
    assert mock_task.summary.startswith("FIXED_AND_VERIFIED:")
    # File actually updated on disk
    calc = temp_workspace / "src" / "calculator.py"
    assert calc.read_text(encoding="utf-8") == new_content


# ---------------------------------------------------------------------------
# Test H: Existing Rejection Path
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_rejection_path_prevents_patch_application_and_testing() -> None:
    user = User(id=uuid.uuid4(), email="reviewer@example.com", display_name="reviewer")
    task_id = uuid.uuid4()
    change_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    mock_task = Task(
        id=task_id,
        repository_id=uuid.uuid4(),
        user_id=user.id,
        title="Task to reject",
        status=TaskStatus.AWAITING_APPROVAL,
    )
    mock_change = ProposedChange(
        id=change_id,
        task_id=task_id,
        summary="Doubtful fix",
        patch_unified="diff",
        status=ChangeStatus.AWAITING_APPROVAL,
    )
    mock_approval = Approval(
        id=approval_id,
        task_id=task_id,
        proposed_change_id=change_id,
        kind=ApprovalKind.APPLY_CHANGES,
        decision=None,
    )

    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    appr_res = MagicMock()
    appr_res.scalar_one_or_none.return_value = mock_approval

    change_res = MagicMock()
    change_res.scalar_one_or_none.return_value = mock_change

    task_res = MagicMock()
    task_res.scalar_one_or_none.return_value = mock_task

    seq_res = MagicMock()
    seq_res.scalar_one.return_value = 2

    mock_session.execute.side_effect = [appr_res, change_res, task_res, seq_res]

    service = ChangeService(mock_session)
    res_approval = await service.decide_approval(
        approval_id=approval_id,
        decision=ApprovalDecision.REJECTED,
        decided_by=user,
        notes="Risk too high",
    )

    # Invariants for rejection:
    assert res_approval.decision == ApprovalDecision.REJECTED
    assert mock_change.status == ChangeStatus.REJECTED
    assert mock_task.status == TaskStatus.REJECTED
    assert "Proposed changes rejected by reviewer: Risk too high" in (mock_task.summary or "")
