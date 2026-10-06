"""Task orchestrator: coordinates agents, state transitions, events and approvals."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.models.change import Approval, ChangeFile, ProposedChange
from app.models.enums import (
    ApprovalKind,
    ChangeStatus,
    ChangeType,
    EventLevel,
    TaskStatus,
    TaskType,
)
from app.models.task import Task, TaskEvent
from app.orchestration.budgets import BudgetTracker
from app.orchestration.proposal_validator import validate_proposal_before_approval
from app.orchestration.state_machine import validate_transition
from app.retrieval.hybrid import HybridRetriever
from app.tools.base import SandboxExecutor, ToolContext
from app.tools.permissions import permissions_for_status
from app.tools.registry import ToolRegistry

logger = get_logger(__name__)


def extract_or_build_proposal(tool_context: ToolContext, debug_text: str, workspace: Path) -> dict[str, Any] | None:
    """Extract proposed patch from tool context (propose_patch tool).

    Speculative regex fallbacks that search arbitrary files or parse unstructured
    LLM prose are disabled for safety and correctness.
    """
    # 1. Multiple patches recorded via ProposePatchTool
    patches = getattr(tool_context, "proposed_patches", None)
    if patches and len(patches) > 0:
        files: list[dict[str, Any]] = []
        diffs: list[str] = []
        for p in patches:
            change_type = (
                ChangeType.ADD
                if p.get("change_type") in ("add", ChangeType.ADD) or p.get("is_new_file")
                else ChangeType.MODIFY
            )
            files.append(
                {
                    "path": p["path"],
                    "change_type": change_type,
                    "unified_diff": p.get("unified_diff", ""),
                    "original_content": p.get("original_content"),
                    "proposed_content": p.get("proposed_content"),
                    "old_str": p.get("old_str"),
                    "new_str": p.get("new_str"),
                    "evidence": p.get("evidence", ""),
                }
            )
            if p.get("unified_diff"):
                diffs.append(p["unified_diff"])
        return {
            "path": patches[0]["path"],
            "files": files,
            "unified_diff": "\n".join(diffs),
            "explanation": patches[0].get("explanation") or debug_text[:500],
            "evidence": patches[0].get("evidence") or "",
        }

    # 2. Single patch recorded via ProposePatchTool
    single_patch = getattr(tool_context, "proposed_patch", None)
    if single_patch:
        change_type = (
            ChangeType.ADD
            if single_patch.get("change_type") in ("add", ChangeType.ADD) or single_patch.get("is_new_file")
            else ChangeType.MODIFY
        )
        file_info = {
            "path": single_patch["path"],
            "change_type": change_type,
            "unified_diff": single_patch.get("unified_diff", ""),
            "original_content": single_patch.get("original_content"),
            "proposed_content": single_patch.get("proposed_content"),
            "old_str": single_patch.get("old_str"),
            "new_str": single_patch.get("new_str"),
            "evidence": single_patch.get("evidence", ""),
        }
        return {
            "path": single_patch["path"],
            "files": [file_info],
            "unified_diff": single_patch.get("unified_diff", ""),
            "explanation": single_patch.get("explanation") or debug_text[:500],
            "evidence": single_patch.get("evidence") or "",
        }

    return None


class TaskOrchestrator:
    """Coordinates execution of a single task across multiple specialized agents."""

    def __init__(
        self,
        session: AsyncSession,
        llm: LLMProvider,
        registry: ToolRegistry,
        settings: Settings | None = None,
        sandbox: SandboxExecutor | None = None,
        event_sink: Callable[[str, str, dict[str, Any] | None], Any] | None = None,
    ) -> None:
        self.session = session
        self.llm = llm
        self.registry = registry
        self.settings = settings or get_settings()
        self.sandbox = sandbox
        self.event_sink = event_sink
        self._seq = 0

    async def emit_event(
        self,
        task: Task,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None = None,
        level: EventLevel = EventLevel.INFO,
    ) -> TaskEvent:
        if self._seq == 0:
            res = await self.session.execute(
                select(func.coalesce(func.max(TaskEvent.seq), 0)).where(TaskEvent.task_id == task.id)
            )
            max_db_seq = res.scalar_one() or 0
            pending_max = max(
                (obj.seq for obj in self.session.new if isinstance(obj, TaskEvent) and obj.task_id == task.id),
                default=0,
            )
            self._seq = max(max_db_seq, pending_max)

        self._seq += 1
        pending_max = max(
            (obj.seq for obj in self.session.new if isinstance(obj, TaskEvent) and obj.task_id == task.id),
            default=0,
        )
        if self._seq <= pending_max:
            self._seq = pending_max + 1
        event = TaskEvent(
            task_id=task.id,
            seq=self._seq,
            event_type=event_type,
            level=level,
            message=message,
            payload=payload,
        )
        self.session.add(event)
        await self.session.flush()

        if self.event_sink:
            try:
                res = self.event_sink(event_type, message, payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:
                logger.warning("event_sink_failed", error=str(exc))

        return event

    async def _transition(
        self, task: Task, target: TaskStatus, message: str, tool_context: ToolContext | None = None
    ) -> None:
        validate_transition(task.status, target)
        task.status = target
        if tool_context is not None:
            tool_context.task_status = target
        await self.emit_event(task, "status_change", message, {"new_status": target.value})
        await self.session.commit()

    async def execute_task(self, task: Task, workspace: Path) -> TaskStatus:
        """Run the end-to-end task execution pipeline."""
        from app.core.logging import bind_context

        bind_context(task_id=str(task.id), repository_id=str(task.repository_id))
        budget = BudgetTracker.from_settings(self.settings)
        retriever = HybridRetriever(repository_id=task.repository_id, session=self.session)

        async def _tool_notify(ev_type: str, msg: str, data: dict[str, Any] | None) -> None:
            await self.emit_event(task, ev_type, msg, data)

        tool_context = ToolContext(
            task_id=task.id,
            agent=task.type.value,  # type: ignore[arg-type]
            workspace=workspace,
            settings=self.settings,
            search=retriever,
            sandbox=self.sandbox,
            emit=_tool_notify,
            session=self.session,
            task_status=task.status,
        )

        # Seed RAG search on task title and description to help planner, codebase, debugger
        target_files = None
        if task.plan and isinstance(task.plan, dict):
            target_files = task.plan.get("target_files")

        rag_snippets: list[str] = []
        repo_context_data: list[dict[str, Any]] = []
        if retriever:
            try:
                hits = await retriever.retrieve_task_context(
                    task.title,
                    task.description or "",
                    target_files=target_files,
                    top_k=6,
                )
                for h in hits:
                    rag_snippets.append(
                        f"File: {h.path} (lines {h.start_line}-{h.end_line}, score={h.score:.2f}, reason={h.reason}):\n{h.content}"
                    )
                    repo_context_data.append(
                        {
                            "path": h.path,
                            "symbol": h.symbol_name,
                            "score": round(h.score, 2),
                            "reason": h.reason or "Relevant to task query",
                            "lines": f"{h.start_line}-{h.end_line}",
                        }
                    )
            except Exception as e:
                logger.warning("rag_search_error", error=str(e))
        rag_context_str = "\n\n".join(rag_snippets)

        prev_failure = ""
        if task.plan and isinstance(task.plan, dict):
            pf = task.plan.get("previous_failure")
            if pf:
                prev_failure = pf.get("reason") or pf.get("exception") or str(pf) if isinstance(pf, dict) else str(pf)

        from app.agents.codebase.codebase import CodebaseAgent
        from app.agents.debugger.debugger import DebuggerAgent
        from app.agents.planner.planner import PlannerAgent

        try:
            if repo_context_data:
                await self.emit_event(
                    task,
                    "context_retrieved",
                    f"Retrieved {len(repo_context_data)} relevant code sections from repository",
                    {"items": repo_context_data},
                )

            # 1. PLANNING
            budget.start_stage("PLANNING", max_steps=4, max_tool_calls=8)
            await self._transition(task, TaskStatus.PLANNING, "Starting planning phase", tool_context)
            planner = PlannerAgent(self.llm, self.registry)
            plan_text = await planner.run(
                task,
                tool_context,
                permissions_for_status(TaskStatus.PLANNING),
                budget,
                self.session,
                extra_context={"rag_context": rag_context_str, "previous_failure": prev_failure},
            )
            current_plan = dict(task.plan) if (task.plan and isinstance(task.plan, dict)) else {}
            current_plan["text"] = plan_text
            current_plan["repository_context"] = repo_context_data
            task.plan = current_plan
            await self.emit_event(task, "plan_created", "Plan formulated by Planner agent", {"plan": plan_text[:500]})

            # 2. ANALYZING
            budget.start_stage("ANALYZING", max_steps=6, max_tool_calls=12)
            await self._transition(task, TaskStatus.ANALYZING, "Analyzing codebase structure", tool_context)
            codebase = CodebaseAgent(self.llm, self.registry)
            analysis_text = await codebase.run(
                task,
                tool_context,
                permissions_for_status(TaskStatus.ANALYZING),
                budget,
                self.session,
                extra_context={"plan": plan_text, "rag_context": rag_context_str, "previous_failure": prev_failure},
            )
            await self.emit_event(task, "analysis_completed", "Codebase analysis completed")

            # 3. INVESTIGATING
            budget.start_stage("INVESTIGATING", max_steps=8, max_tool_calls=16)
            await self._transition(
                task, TaskStatus.INVESTIGATING, "Investigating solution and formulating fix", tool_context
            )

            # Automated reproduction before running Debugger
            repro_test_run = None
            repro_text = ""
            repro_result_dict = None
            if task.type in (TaskType.BUG, TaskType.BUG_FIX):
                repro_test_run, repro_result_dict, repro_text = await self._run_reproduction(task, workspace)

            debugger = DebuggerAgent(self.llm, self.registry)
            debug_text = await debugger.run(
                task,
                tool_context,
                permissions_for_status(TaskStatus.INVESTIGATING),
                budget,
                self.session,
                extra_context={
                    "code_context": analysis_text,
                    "rag_context": rag_context_str,
                    "repository_context": repo_context_data,
                    "test_failures": repro_text,
                    "reproduction": repro_result_dict,
                    "previous_failure": prev_failure,
                },
            )
            task.root_cause = {"analysis": debug_text}
            task.budget_usage = budget.to_dict()

            # Question tasks terminate here with findings
            if task.type == TaskType.QUESTION:
                task.summary = debug_text
                await self._transition(task, TaskStatus.COMPLETED, "Question answered successfully", tool_context)
                return TaskStatus.COMPLETED

            # 4. FIX PROPOSED & AWAITING APPROVAL
            patch_data = extract_or_build_proposal(tool_context, debug_text, workspace)

            if not patch_data:
                defect_confirmed, defect_evidence = self._classify_defect(debug_text, repro_test_run)

                if task.type in (TaskType.BUG, TaskType.BUG_FIX):
                    if defect_confirmed:
                        fail_reason = (
                            "Agent confirmed defect but failed to produce a valid structured patch proposal."
                        )
                        task.root_cause = {
                            "outcome": "BUG_CONFIRMED_BUT_PROPOSAL_FAILED",
                            "evidence": defect_evidence,
                            "reason": fail_reason,
                            "investigation_notes": debug_text,
                        }
                        task.summary = (
                            f"BUG_CONFIRMED_BUT_PROPOSAL_FAILED: {defect_evidence}. {fail_reason}"
                        )
                        task.error = {
                            "reason": fail_reason,
                            "outcome": "BUG_CONFIRMED_BUT_PROPOSAL_FAILED",
                            "evidence": defect_evidence,
                        }
                        await self.emit_event(
                            task,
                            "proposal_generation_failed",
                            f"Defect confirmed but structured proposal generation failed: {defect_evidence}",
                            {
                                "outcome": "BUG_CONFIRMED_BUT_PROPOSAL_FAILED",
                                "evidence": defect_evidence,
                                "summary": task.summary,
                            },
                            level=EventLevel.ERROR,
                        )
                        await self._transition(
                            task,
                            TaskStatus.FAILED,
                            "Defect confirmed but proposal generation failed",
                            tool_context,
                        )
                        return TaskStatus.FAILED
                    else:
                        task.root_cause = {
                            "outcome": "NO_CONFIRMED_BUG",
                            "evidence": "No reproducible defect was established from repository evidence. No files were modified.",
                            "investigation_notes": debug_text,
                        }
                        task.summary = "NO_CONFIRMED_BUG: No reproducible defect was established from repository evidence. No files were modified."
                        await self.emit_event(
                            task,
                            "no_confirmed_bug",
                            "No reproducible defect was established from repository evidence. No files were modified.",
                            {"outcome": "NO_CONFIRMED_BUG", "summary": task.summary},
                        )
                        await self._transition(
                            task, TaskStatus.COMPLETED, "No reproducible defect established", tool_context
                        )
                        return TaskStatus.COMPLETED
                else:
                    task.summary = debug_text
                    await self._transition(
                        task, TaskStatus.COMPLETED, "Investigation completed with recommendations", tool_context
                    )
                    return TaskStatus.COMPLETED

            # Validate patch in isolated temporary workspace BEFORE creating any records or moving to FIX_PROPOSED
            is_valid, val_reason = validate_proposal_before_approval(workspace, patch_data)
            if not is_valid:
                logger.error("proposed_patch_validation_failed", task_id=str(task.id), reason=val_reason)
                task.error = {"reason": f"Proposed patch failed pre-approval validation: {val_reason}"}
                await self._transition(
                    task,
                    TaskStatus.FAILED,
                    f"Fix proposal rejected by pre-approval validation: {val_reason}",
                    tool_context,
                )
                await self.emit_event(
                    task,
                    "patch_validation_failed",
                    f"Fix proposal rejected by pre-approval validation: {val_reason}",
                    {"new_status": TaskStatus.FAILED.value, "reason": val_reason},
                    level=EventLevel.ERROR,
                )
                await self.session.commit()
                return TaskStatus.FAILED

            # Persist ProposedChange + ChangeFiles FIRST
            evidence_info = (
                patch_data.get("evidence") or patch_data.get("explanation") or "Automated fix generated by DevAgent"
            )
            proposal = ProposedChange(
                task_id=task.id,
                iteration=task.iteration,
                status=ChangeStatus.AWAITING_APPROVAL,
                summary=task.title,
                explanation=debug_text[:1000],
                rationale=str(evidence_info)[:1000],
                patch_unified=patch_data["unified_diff"],
                files_changed=len(patch_data.get("files", [patch_data])),
                root_cause={"evidence": evidence_info, "outcome": "FIX_PROPOSED"},
            )
            self.session.add(proposal)
            await self.session.flush()

            files_list = patch_data.get("files", [patch_data])
            for f_info in files_list:
                change_file = ChangeFile(
                    proposed_change_id=proposal.id,
                    task_id=task.id,
                    path=f_info["path"],
                    change_type=f_info.get("change_type", ChangeType.MODIFY),
                    diff=f_info.get("unified_diff", f_info.get("diff", "")),
                    original_content=f_info.get("original_content"),
                    proposed_content=f_info.get("proposed_content"),
                )
                self.session.add(change_file)
            await self.session.flush()

            # ONLY THEN transition to FIX_PROPOSED
            await self._transition(task, TaskStatus.FIX_PROPOSED, "Fix proposed with code diff", tool_context)

            # Persist Approval
            approval = Approval(
                task_id=task.id,
                proposed_change_id=proposal.id,
                kind=ApprovalKind.APPLY_CHANGES,
                decision=None,
                requested_at=datetime.now(UTC),
            )
            self.session.add(approval)
            await self.session.flush()

            # Transition to AWAITING_APPROVAL
            await self._transition(
                task, TaskStatus.AWAITING_APPROVAL, "Changes require user approval before applying", tool_context
            )
            return task.status

        except Exception as exc:
            logger.error("task_execution_failed", task_id=str(task.id), error=str(exc))
            task.error = {"exception": str(exc), "type": type(exc).__name__}
            task.status = TaskStatus.FAILED
            await self.emit_event(
                task,
                "status_change",
                f"Task failed: {exc}",
                {"new_status": TaskStatus.FAILED.value, "error": str(exc)},
                level=EventLevel.ERROR,
            )
            await self.emit_event(
                task,
                "task_failed",
                f"Execution failed: {exc}",
                {"new_status": TaskStatus.FAILED.value, "error": str(exc)},
                level=EventLevel.ERROR,
            )
            await self.session.commit()
            return TaskStatus.FAILED

    async def _run_reproduction(
        self,
        task: Task,
        workspace: Path,
    ) -> tuple[Any, dict[str, Any] | None, str]:
        """Execute automated test reproduction in sandbox if configured/available."""
        user_test_cmd = None
        if task.plan and isinstance(task.plan, dict):
            user_test_cmd = task.plan.get("test_command")

        test_cmd: list[str] | None = None
        if user_test_cmd:
            import shlex

            parsed = shlex.split(user_test_cmd)
            test_cmd = parsed if parsed else ["pytest"]
        elif await asyncio.to_thread(
            lambda: (workspace / "test_app.py").is_file()
            or (workspace / "tests").is_dir()
            or any(workspace.glob("test_*.py"))
            or any(workspace.glob("*_test.py"))
        ):
            test_cmd = ["pytest"]

        if not test_cmd or self.sandbox is None:
            return None, None, ""

        try:
            from app.services.test_service import TestService

            test_service = TestService(self.session, self.settings)
            test_run = await test_service.run_tests(
                task.id,
                test_cmd,
                self.sandbox,
                iteration=task.iteration,
                phase="reproduction",
            )
            stdout_str = test_run.stdout_tail or ""
            stderr_str = test_run.stderr_tail or ""
            repro_output = f"{stdout_str}\n{stderr_str}".strip()

            repro_dict = {
                "command": test_cmd,
                "exit_code": test_run.exit_code,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "duration_ms": test_run.duration_ms,
                "summary": test_run.summary,
                "all_passed": test_run.all_passed,
                "passed": test_run.passed,
                "failed": test_run.failed,
                "errors": test_run.errors,
            }

            repro_text = (
                f"REPRODUCTION COMMAND: {' '.join(test_cmd)}\n"
                f"EXIT CODE: {test_run.exit_code}\n"
                f"TEST SUMMARY: {test_run.summary}\n"
                f"OUTPUT:\n{repro_output}"
            )

            await self.emit_event(
                task,
                "test_reproduction",
                f"Reproduction command '{' '.join(test_cmd)}' completed: {test_run.summary} (exit {test_run.exit_code})",
                repro_dict,
                level=EventLevel.WARNING if not test_run.all_passed else EventLevel.INFO,
            )
            return test_run, repro_dict, repro_text
        except Exception as exc:
            logger.warning("reproduction_execution_failed", error=str(exc))
            return None, None, ""

    def _classify_defect(
        self,
        debug_text: str,
        repro_test_run: Any,
    ) -> tuple[bool, str]:
        """Classify whether the investigation established a confirmed defect."""
        if repro_test_run is not None and not repro_test_run.all_passed:
            evidence = (
                f"Reproduction test failed with exit code {repro_test_run.exit_code}: "
                f"{repro_test_run.summary}"
            )
            return True, evidence

        from app.agents.debugger.debugger import detects_concrete_defect

        if detects_concrete_defect(debug_text):
            evidence = "Defect identified and confirmed through repository code analysis."
            return True, evidence

        return False, "No reproducible defect was established from repository evidence."
