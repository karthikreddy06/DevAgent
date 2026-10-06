"""Focused regression and unit tests for the bug detection, reproduction,

and structured proposal recovery pipeline.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import extract_tool_calls
from app.agents.debugger.debugger import DebuggerAgent
from app.core.config import Settings
from app.core.errors import ValidationError
from app.core.paths import normalize_relative_path, safe_join
from app.llm.base import LLMResponse, LLMUsage
from app.models.change import Approval, ProposedChange
from app.models.enums import TaskStatus, TaskType
from app.models.task import Task
from app.models.testing import TestRun as ModelTestRun
from app.orchestration.budgets import BudgetTracker
from app.orchestration.orchestrator import TaskOrchestrator, extract_or_build_proposal
from app.tools import create_default_registry
from app.tools.base import SandboxOutput, ToolContext, ToolResult
from app.tools.docker.runner import SandboxLimits, build_container_kwargs
from app.tools.permissions import permissions_for_status
from app.tools.write import ProposePatchArgs, ProposePatchTool

ModelTestRun.__test__ = False


@pytest.fixture
def bug_test_workspace(temp_workspace: Path) -> Path:
    """Workspace mirroring devagent-bug-test scenario."""
    app_py = temp_workspace / "app.py"
    app_py.write_text(
        "def calculate_total(price, tax):\n    # BUG: tax is incorrectly subtracted instead of added.\n    return price - tax\n",
        encoding="utf-8",
    )
    test_app_py = temp_workspace / "test_app.py"
    test_app_py.write_text(
        "from app import calculate_total\n\n\ndef test_calculate_total():\n    assert calculate_total(100, 10) == 110\n",
        encoding="utf-8",
    )
    return temp_workspace


def create_mock_session():
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
    return mock_session, added_objects


# ---------------------------------------------------------------------------
# Test 1: Recovery prompt contains known target file
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_recovery_prompt_contains_known_target_file(bug_test_workspace: Path) -> None:
    debugger = DebuggerAgent(AsyncMock(), create_default_registry())
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
    )
    tool_ctx = ToolContext(
        task_id=task.id,
        agent="debugger",
        workspace=bug_test_workspace,
        settings=MagicMock(),
    )
    recovery_prompt = debugger.get_recovery_prompt(
        task,
        tool_ctx,
        "The bug is located in calculate_total in app.py. return price - tax should be return price + tax.",
        extra_context={
            "repository_context": [
                {"path": "app.py", "symbol": "calculate_total"},
                {"path": "test_app.py", "symbol": "test_calculate_total"},
            ],
            "test_failures": "assert 90 == 110",
        },
    )

    assert recovery_prompt is not None
    assert "Target file:\napp.py" in recovery_prompt
    assert "Target function:\ncalculate_total" in recovery_prompt
    assert "old_str:\nreturn price - tax" in recovery_prompt
    assert "new_str:\nreturn price + tax" in recovery_prompt


# ---------------------------------------------------------------------------
# Test 2: Recovery prompt requires repository-relative path
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_recovery_prompt_requires_repository_relative_path(bug_test_workspace: Path) -> None:
    debugger = DebuggerAgent(AsyncMock(), create_default_registry())
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
    )
    tool_ctx = ToolContext(
        task_id=task.id,
        agent="debugger",
        workspace=bug_test_workspace,
        settings=MagicMock(),
    )
    recovery_prompt = debugger.get_recovery_prompt(
        task,
        tool_ctx,
        "subtracting tax instead of adding it",
        extra_context={
            "repository_context": [{"path": "app.py", "symbol": "calculate_total"}],
            "test_failures": "assert 90 == 110",
        },
    )

    assert recovery_prompt is not None
    assert 'path MUST be repository-relative: use "app.py", NOT "/app.py"' in recovery_prompt
    assert 'Do NOT use "/workspace/..."' in recovery_prompt
    assert 'Do NOT invent a filename from the function name' in recovery_prompt


# ---------------------------------------------------------------------------
# Test 3: Structured nested args are parsed
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_structured_nested_args_are_parsed() -> None:
    raw = (
        '```json\n'
        '{\n'
        '  "tool": "propose_patch",\n'
        '  "args": {\n'
        '    "path": "app.py",\n'
        '    "old_str": "return price - tax",\n'
        '    "new_str": "return price + tax"\n'
        '  }\n'
        '}\n'
        '```'
    )
    calls = extract_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0]["tool"] == "propose_patch"
    assert calls[0]["args"]["path"] == "app.py"
    assert calls[0]["args"]["old_str"] == "return price - tax"
    assert calls[0]["args"]["new_str"] == "return price + tax"


# ---------------------------------------------------------------------------
# Test 4: Structured top-level args are parsed
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_structured_top_level_args_are_parsed() -> None:
    raw = (
        '```json\n'
        '{\n'
        '  "tool": "propose_patch",\n'
        '  "path": "app.py",\n'
        '  "old_str": "return price - tax",\n'
        '  "new_str": "return price + tax",\n'
        '  "explanation": "Fix tax calculation"\n'
        '}\n'
        '```'
    )
    calls = extract_tool_calls(raw)
    assert len(calls) == 1
    assert calls[0]["tool"] == "propose_patch"
    assert calls[0]["args"]["path"] == "app.py"
    assert calls[0]["args"]["old_str"] == "return price - tax"
    assert calls[0]["args"]["new_str"] == "return price + tax"
    assert calls[0]["args"]["explanation"] == "Fix tax calculation"


# ---------------------------------------------------------------------------
# Test 5: Prose is NOT treated as a patch
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_prose_is_not_treated_as_patch(temp_workspace: Path) -> None:
    prose = (
        "The bug in calculate_total in app.py is that tax is subtracted. "
        "It should be changed to: return price + tax."
    )
    calls = extract_tool_calls(prose)
    assert len(calls) == 0

    tool_ctx = ToolContext(task_id=uuid.uuid4(), agent="debugger", workspace=temp_workspace, settings=MagicMock())
    proposal = extract_or_build_proposal(tool_ctx, prose, temp_workspace)
    assert proposal is None


# ---------------------------------------------------------------------------
# Test 6: Markdown diff is NOT treated as a patch
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_markdown_diff_is_not_treated_as_patch(temp_workspace: Path) -> None:
    diff_text = (
        "Here is the diff to apply:\n\n"
        "```diff\n"
        "--- a/app.py\n"
        "+++ b/app.py\n"
        "@@ -1,3 +1,3 @@\n"
        "- return price - tax\n"
        "+ return price + tax\n"
        "```"
    )
    calls = extract_tool_calls(diff_text)
    assert len(calls) == 0

    tool_ctx = ToolContext(task_id=uuid.uuid4(), agent="debugger", workspace=temp_workspace, settings=MagicMock())
    proposal = extract_or_build_proposal(tool_ctx, diff_text, temp_workspace)
    assert proposal is None


# ---------------------------------------------------------------------------
# Test 7: Absolute paths remain rejected
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_absolute_paths_remain_rejected(bug_test_workspace: Path) -> None:
    with pytest.raises(ValidationError, match="Absolute paths are not allowed"):
        normalize_relative_path("/app.py")

    with pytest.raises(ValidationError, match="Absolute paths are not allowed"):
        safe_join(bug_test_workspace, "/app/calculate_total.py")

    tool = ProposePatchTool()
    tool_ctx = ToolContext(task_id=uuid.uuid4(), agent="debugger", workspace=bug_test_workspace, settings=MagicMock())
    args = ProposePatchArgs(path="/app/calculate_total.py", new_str="return price + tax")
    res = await tool.run(args, tool_ctx)
    assert res.ok is False
    assert "Absolute paths are not allowed" in res.error
    assert tool_ctx.proposed_patch is None


# ---------------------------------------------------------------------------
# Test 8: Traversal paths remain rejected
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_traversal_paths_remain_rejected(bug_test_workspace: Path) -> None:
    with pytest.raises(ValidationError, match="Path traversal is not allowed"):
        normalize_relative_path("../outside.py")

    with pytest.raises(ValidationError, match="Path traversal is not allowed"):
        safe_join(bug_test_workspace, "../outside.py")


# ---------------------------------------------------------------------------
# Test 9: Tool error receives one controlled correction prompt
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_tool_error_receives_one_controlled_correction_prompt(bug_test_workspace: Path) -> None:
    debugger = DebuggerAgent(AsyncMock(), create_default_registry())
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
    )
    tool_ctx = ToolContext(task_id=task.id, agent="debugger", workspace=bug_test_workspace, settings=MagicMock())
    tool_args = {"path": "/app/calculate_total.py", "old_str": "return price - tax", "new_str": "return price + tax"}
    tool_result = ToolResult.failure("validation_error: Absolute paths are not allowed")

    correction = debugger.get_tool_error_correction_prompt(
        task,
        tool_ctx,
        "propose_patch",
        tool_args,
        tool_result,
        extra_context={"repository_context": [{"path": "app.py", "symbol": "calculate_total"}]},
    )

    assert correction is not None
    assert "propose_patch was rejected because the path is absolute" in correction
    assert "For this target the correct path is app.py" in correction
    assert 'Do not output prose or a shell command' in correction
    assert '"path": "app.py"' in correction


# ---------------------------------------------------------------------------
# Test 10: Corrected structured propose_patch succeeds
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_corrected_structured_propose_patch_succeeds(
    bug_test_workspace: Path, test_settings: Settings
) -> None:
    session, _ = create_mock_session()
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
    )
    tool_ctx = ToolContext(
        task_id=task.id,
        agent="debugger",
        workspace=bug_test_workspace,
        settings=test_settings,
        session=session,
    )
    budget = BudgetTracker.from_settings(test_settings)
    budget.start_stage("INVESTIGATING", max_steps=8, max_tool_calls=16)

    mock_llm = AsyncMock()
    mock_llm.model = "test-model"
    mock_llm.name = "test-provider"

    # Turn 1: Prose diagnosing defect
    turn_1 = "The bug is in calculate_total in app.py. return price - tax should be return price + tax."
    # Turn 2: Erroneous tool call with absolute path
    turn_2 = (
        '```json\n'
        '{\n'
        '  "tool": "propose_patch",\n'
        '  "args": {\n'
        '    "path": "/app/calculate_total.py",\n'
        '    "old_str": "return price - tax",\n'
        '    "new_str": "return price + tax"\n'
        '  }\n'
        '}\n'
        '```'
    )
    # Turn 3: Corrected tool call with relative path "app.py"
    turn_3 = (
        '```json\n'
        '{\n'
        '  "tool": "propose_patch",\n'
        '  "args": {\n'
        '    "path": "app.py",\n'
        '    "old_str": "return price - tax",\n'
        '    "new_str": "return price + tax"\n'
        '  }\n'
        '}\n'
        '```'
    )
    # Turn 4: Final statement
    turn_4 = "The patch has been proposed successfully for app.py."

    mock_llm.complete = AsyncMock(
        side_effect=[
            LLMResponse(text=turn_1, model="test-model", provider="test-provider", usage=LLMUsage(100, 50)),
            LLMResponse(text=turn_2, model="test-model", provider="test-provider", usage=LLMUsage(150, 50)),
            LLMResponse(text=turn_3, model="test-model", provider="test-provider", usage=LLMUsage(200, 50)),
            LLMResponse(text=turn_4, model="test-model", provider="test-provider", usage=LLMUsage(250, 30)),
        ]
    )

    debugger = DebuggerAgent(mock_llm, create_default_registry())
    await debugger.run(
        task,
        tool_ctx,
        permissions_for_status(TaskStatus.INVESTIGATING),
        budget,
        session,
        extra_context={
            "repository_context": [{"path": "app.py", "symbol": "calculate_total"}],
            "test_failures": "assert 90 == 110",
        },
    )

    # Patch is successfully recorded on tool_ctx
    assert tool_ctx.proposed_patch is not None
    assert tool_ctx.proposed_patch["path"] == "app.py"
    assert tool_ctx.proposed_patch["old_str"] == "return price - tax"
    assert tool_ctx.proposed_patch["new_str"] == "return price + tax"


# ---------------------------------------------------------------------------
# Test 11: Incorrect correction results in BUG_CONFIRMED_BUT_PROPOSAL_FAILED
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_incorrect_correction_results_in_bug_confirmed_but_proposal_failed(
    bug_test_workspace: Path, test_settings: Settings
) -> None:
    session, added = create_mock_session()
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
        status=TaskStatus.CREATED,
    )

    mock_llm = AsyncMock()
    mock_sandbox = AsyncMock()
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxOutput(
            exit_code=1,
            stdout="assert 90 == 110\n==== 1 failed ====",
            stderr="",
        )
    )

    orchestrator = TaskOrchestrator(
        session=session,
        llm=mock_llm,
        registry=create_default_registry(),
        settings=test_settings,
        sandbox=mock_sandbox,
    )

    # Debugger returns diagnosis but fails to emit valid propose_patch
    hypothesis_text = "Defect is confirmed in app.py. return price - tax should be return price + tax."

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", new_callable=AsyncMock) as mock_debug,
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan"
        mock_code.return_value = "Code analysis"
        mock_debug.return_value = hypothesis_text
        mock_rag.return_value = [{"path": "app.py", "symbol": "calculate_total"}]

        final_status = await orchestrator.execute_task(task, bug_test_workspace)

    assert final_status == TaskStatus.FAILED
    assert task.status == TaskStatus.FAILED
    assert task.root_cause["outcome"] == "BUG_CONFIRMED_BUT_PROPOSAL_FAILED"
    assert "BUG_CONFIRMED_BUT_PROPOSAL_FAILED" in task.summary
    assert len([o for o in added if isinstance(o, ProposedChange)]) == 0
    assert len([o for o in added if isinstance(o, Approval)]) == 0


# ---------------------------------------------------------------------------
# Test 12: Confirmed bug is never classified as NO_CONFIRMED_BUG on proposal failure
# ---------------------------------------------------------------------------
@pytest.mark.unit
def test_confirmed_bug_is_never_classified_as_no_confirmed_bug_on_proposal_failure(
    test_settings: Settings,
) -> None:
    orchestrator = TaskOrchestrator(
        session=AsyncMock(),
        llm=AsyncMock(),
        registry=create_default_registry(),
        settings=test_settings,
    )
    fake_repro_run = MagicMock()
    fake_repro_run.all_passed = False
    fake_repro_run.exit_code = 1
    fake_repro_run.summary = "0 passed, 1 failed, 0 errors"

    is_confirmed, evidence = orchestrator._classify_defect(
        "I could not propose a patch.",
        fake_repro_run,
    )
    assert is_confirmed is True
    assert "exit code 1" in evidence
    assert "0 passed, 1 failed" in evidence


# ---------------------------------------------------------------------------
# Test 13: Existing NO_CONFIRMED_BUG path still works
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_existing_no_confirmed_bug_path_still_works(
    temp_workspace: Path, test_settings: Settings
) -> None:
    session, added = create_mock_session()
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Verify calculator behavior",
        type=TaskType.BUG_FIX,
        status=TaskStatus.CREATED,
    )

    mock_llm = AsyncMock()
    mock_sandbox = AsyncMock()
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxOutput(
            exit_code=0,
            stdout="==== 1 passed in 0.01s ====",
            stderr="",
        )
    )

    orchestrator = TaskOrchestrator(
        session=session,
        llm=mock_llm,
        registry=create_default_registry(),
        settings=test_settings,
        sandbox=mock_sandbox,
    )

    no_bug_text = "All tests pass. No defect found. Conforms to specification."

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", new_callable=AsyncMock) as mock_debug,
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan"
        mock_code.return_value = "Code analysis"
        mock_debug.return_value = no_bug_text
        mock_rag.return_value = []

        final_status = await orchestrator.execute_task(task, temp_workspace)

    assert final_status == TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert task.root_cause["outcome"] == "NO_CONFIRMED_BUG"
    assert len([o for o in added if isinstance(o, ProposedChange)]) == 0


# ---------------------------------------------------------------------------
# Test 14: Existing approval gate still works
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_existing_approval_gate_still_works(
    bug_test_workspace: Path, test_settings: Settings
) -> None:
    session, added = create_mock_session()
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
        status=TaskStatus.CREATED,
        iteration=1,
        plan={"test_command": "pytest"},
    )

    mock_sandbox = AsyncMock()
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxOutput(
            exit_code=1,
            stdout="assert 90 == 110",
            stderr="",
        )
    )

    orchestrator = TaskOrchestrator(
        session=session,
        llm=AsyncMock(),
        registry=create_default_registry(),
        settings=test_settings,
        sandbox=mock_sandbox,
    )

    async def fake_debugger_run(t, ctx, caps, bgt, sess, extra_context=None):
        patch_tool = ProposePatchTool()
        args = ProposePatchArgs(
            path="app.py",
            old_str="return price - tax",
            new_str="return price + tax",
            explanation="Fix calculate_total",
            evidence="reproduction test failed",
        )
        res = await patch_tool.run(args, ctx)
        assert res.ok is True
        return "Fix proposed"

    with (
        patch("app.agents.planner.planner.PlannerAgent.run", new_callable=AsyncMock) as mock_plan,
        patch("app.agents.codebase.codebase.CodebaseAgent.run", new_callable=AsyncMock) as mock_code,
        patch("app.agents.debugger.debugger.DebuggerAgent.run", side_effect=fake_debugger_run),
        patch("app.retrieval.hybrid.HybridRetriever.retrieve_task_context", new_callable=AsyncMock) as mock_rag,
    ):
        mock_plan.return_value = "Plan"
        mock_code.return_value = "Code analysis"
        mock_rag.return_value = [{"path": "app.py", "symbol": "calculate_total"}]

        final_status = await orchestrator.execute_task(task, bug_test_workspace)

    assert final_status == TaskStatus.AWAITING_APPROVAL
    assert task.status == TaskStatus.AWAITING_APPROVAL

    # Invariants
    proposals = [o for o in added if isinstance(o, ProposedChange)]
    approvals = [o for o in added if isinstance(o, Approval)]
    assert len(proposals) == 1
    assert len(approvals) == 1

    # Workspace on disk is completely unmodified
    content = (bug_test_workspace / "app.py").read_text(encoding="utf-8")
    assert "return price - tax" in content
    assert "return price + tax" not in content


# ---------------------------------------------------------------------------
# Test 15: Existing sandbox isolation still works
# ---------------------------------------------------------------------------
@pytest.mark.unit
async def test_existing_sandbox_isolation_still_works(
    bug_test_workspace: Path, test_settings: Settings
) -> None:
    session, _ = create_mock_session()
    task = Task(
        id=uuid.uuid4(),
        repository_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        title="Fix calculate_total tax calculation bug",
        type=TaskType.BUG_FIX,
        status=TaskStatus.INVESTIGATING,
        iteration=1,
    )

    mock_sandbox = AsyncMock()
    mock_sandbox.execute = AsyncMock(
        return_value=SandboxOutput(
            exit_code=0,
            stdout="all passed",
            stderr="",
        )
    )

    orchestrator = TaskOrchestrator(
        session=session,
        llm=AsyncMock(),
        registry=create_default_registry(),
        settings=test_settings,
        sandbox=mock_sandbox,
    )

    _test_run, _repro_dict, _repro_text = await orchestrator._run_reproduction(task, bug_test_workspace)
    assert mock_sandbox.execute.call_count == 1
    call_args, call_kwargs = mock_sandbox.execute.call_args
    assert call_args[0] == ["pytest"]
    assert call_kwargs["purpose"] == "Run test suite"

    # Also verify build_container_kwargs enforces strict isolation properties
    limits = SandboxLimits.from_settings(test_settings, network_enabled=False)
    kwargs = build_container_kwargs(
        image="devagent-runner:latest",
        workspace=bug_test_workspace,
        task_id=str(task.id),
        limits=limits,
    )
    assert kwargs["network_mode"] == "none"
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges:true"]
    assert kwargs["privileged"] is False
