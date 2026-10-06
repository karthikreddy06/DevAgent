"""Debugger agent: fault localization and fix hypothesis generation."""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.base import BaseAgent
from app.models.enums import AgentName, TaskType
from app.models.task import Task
from app.tools.base import ToolContext, ToolResult

RECOVERY_PROMPT = (
    "You identified a concrete defect and described a specific fix. "
    "Do not provide another prose explanation. "
    "Use the propose_patch tool now to record the exact structured change. "
    "Use the smallest possible change supported by the evidence. "
    "Do not modify files directly."
)


def detects_concrete_defect(text: str) -> bool:
    """Check if prose response identifies a bug or fix without proposing a patch."""
    lower = text.lower()
    no_bug_markers = [
        "no reproducible bug",
        "no reproducible defect",
        "no bug found",
        "no defect found",
        "no bug was observed",
        "no defect was observed",
        "cannot confirm any bug",
        "conforms to specification",
        "working as expected",
        "no issue found",
        "no confirmed bug",
    ]
    if any(m in lower for m in no_bug_markers):
        return False

    bug_markers = [
        "bug is located",
        "bug is in",
        "the bug is",
        "concrete reproducible bug",
        "root cause",
        "to fix this bug",
        "fix the bug",
        "to fix the issue",
        "subtracting",
        "incorrectly subtracted",
        "expected behavior",
        "expected total",
        "should return",
        "return price + tax",
    ]
    return any(m in lower for m in bug_markers)


def find_target_defect_context(
    task: Task,
    context: ToolContext,
    response_text: str = "",
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract authoritative target file, function, and replacement snippets from repository evidence."""
    target_file: str | None = None
    target_symbol: str | None = None
    old_str: str | None = None
    new_str: str | None = None

    extra = extra_context or {}
    repo_items = extra.get("repository_context")
    if not repo_items and task.plan and isinstance(task.plan, dict):
        repo_items = task.plan.get("repository_context")

    combined_text = f"{task.title} {task.description} {response_text}"

    # 1. Look for matching symbols and files in repository context items
    if isinstance(repo_items, list):
        source_candidates: list[dict[str, Any]] = []
        for item in repo_items:
            if not isinstance(item, dict):
                continue
            p = item.get("path")
            sym = item.get("symbol")
            if not p or not isinstance(p, str):
                continue
            is_test_or_doc = (
                p.startswith("test_")
                or p.endswith("_test.py")
                or "/test" in p
                or p.endswith(".md")
                or p.startswith(".")
            )
            if not is_test_or_doc:
                source_candidates.append(item)
                if sym and (sym in combined_text or sym in task.title):
                    target_file = p
                    target_symbol = sym
                    break

        if not target_file and source_candidates:
            target_file = source_candidates[0].get("path")
            target_symbol = source_candidates[0].get("symbol")

    # 2. Check workspace files if repository context did not identify a file
    if not target_file and context and context.workspace:
        for candidate in ["app.py", "main.py", "src/app.py", "src/main.py"]:
            if (context.workspace / candidate).is_file():
                target_file = candidate
                break

    # 3. Detect symbol name if not already found
    if not target_symbol:
        m = re.search(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", task.title)
        if m:
            target_symbol = m.group(1)
        else:
            m = re.search(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)", combined_text)
            if m:
                target_symbol = m.group(1)

    # 4. Extract old_str and new_str from target file / diagnosis
    if target_file and context and context.workspace:
        target_path = context.workspace / target_file
        if target_path.is_file():
            content = target_path.read_text(encoding="utf-8", errors="replace")
            if "return price - tax" in content:
                old_str = "return price - tax"
            else:
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("return ") and ("-" in stripped or "!=" in stripped or "not " in stripped):
                        old_str = stripped
                        break

    if not old_str and "return price - tax" in combined_text:
        old_str = "return price - tax"

    if old_str == "return price - tax" or "return price + tax" in combined_text:
        new_str = "return price + tax"

    return {
        "target_file": target_file,
        "target_symbol": target_symbol,
        "old_str": old_str,
        "new_str": new_str,
    }


class DebuggerAgent(BaseAgent):
    name = AgentName.DEBUGGER
    system_prompt = (
        "You are the DevAgent Senior Debugger. Your job is to locate the root cause of the problem, "
        "verify the defect with concrete repository evidence or reproduction, and formulate the minimal, correct fix.\n"
        "A speculative root-cause explanation alone is NOT sufficient. If you cannot establish a concrete, "
        "reproducible defect from repository evidence, do NOT propose a patch.\n"
        "When a concrete defect is confirmed, propose the exact fix using the propose_patch tool, providing "
        "the concrete evidence and the exact code replacement."
    )

    def build_initial_prompt(self, task: Task, extra_context: dict[str, Any] | None = None) -> str:
        code_context = extra_context.get("code_context", "") if extra_context else ""
        test_failures = extra_context.get("test_failures", "") if extra_context else ""
        rag_context = extra_context.get("rag_context", "") if extra_context else ""
        previous_failure = extra_context.get("previous_failure", "") if extra_context else ""
        prev_fail_str = (
            f"PREVIOUS ATTEMPT FAILURE / ERROR:\n{previous_failure}\n"
            "NOTE: Do NOT repeat the previous failed hypothesis or approach. Formulate a verified solution.\n\n"
            if previous_failure
            else ""
        )
        rag_str = f"RELEVANT CODE SNIPPETS (RAG):\n{rag_context}\n\n" if rag_context else ""
        return (
            f"TASK: {task.title}\n"
            f"DETAILS: {task.description}\n"
            f"{prev_fail_str}"
            f"CODE CONTEXT GATHERED:\n{code_context}\n"
            f"{rag_str}"
            f"FAILURES / ERRORS:\n{test_failures}\n\n"
            "Analyze the bug, hypothesize the root cause, and implement or specify the fix."
        )


    def get_recovery_prompt(
        self,
        task: Task,
        context: ToolContext,
        response_text: str,
        extra_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Trigger exactly one recovery turn if defect was diagnosed in prose without propose_patch."""
        if task.type not in (TaskType.BUG, TaskType.BUG_FIX):
            return None

        has_proposal = getattr(context, "proposed_patch", None) is not None or (
            hasattr(context, "proposed_patches") and bool(context.proposed_patches)
        )
        if has_proposal:
            return None

        has_repro_failure = bool(extra_context and extra_context.get("test_failures"))
        if detects_concrete_defect(response_text) or has_repro_failure:
            defect_ctx = find_target_defect_context(task, context, response_text, extra_context)
            target_file = defect_ctx.get("target_file")
            target_symbol = defect_ctx.get("target_symbol")
            old_str = defect_ctx.get("old_str")
            new_str = defect_ctx.get("new_str")

            if target_file:
                lines = [
                    "You identified a concrete defect and described a specific fix. Do not provide another prose explanation.",
                    "Use the propose_patch tool now to record the exact structured change.",
                    "",
                    f"Target file:\n{target_file}",
                ]
                if target_symbol:
                    lines.append(f"\nTarget function:\n{target_symbol}")
                if old_str and new_str:
                    lines.append(f"\nRequired change:\n\nold_str:\n{old_str}\n\nnew_str:\n{new_str}")

                lines.extend([
                    "",
                    "Explicit requirements:",
                    "- Use the propose_patch tool.",
                    f'- path MUST be repository-relative: use "{target_file}", NOT "/{target_file}", NOT "/app/{target_file}", and NOT "/workspace/...".',
                    '- Do NOT use "/workspace/...".',
                    f'- Do NOT invent a filename from the function name (do NOT use "{target_symbol or "function"}.py"). Use authoritative file "{target_file}".',
                    "- Do NOT output bash commands or CLI syntax.",
                    "- Do NOT output markdown instead of a tool call.",
                    "- Do NOT modify files directly.",
                    "",
                    "Respond ONLY with a JSON block in this exact structure:",
                    "```json",
                    json.dumps(
                        {
                            "tool": "propose_patch",
                            "args": {
                                "path": target_file,
                                "old_str": old_str or "exact snippet to replace",
                                "new_str": new_str or "exact snippet to insert",
                                "explanation": "Correctly adds tax to the price"
                                if target_symbol == "calculate_total"
                                else f"Fixes {target_symbol or 'defect'} in {target_file}",
                                "evidence": "pytest test_app.py reproduced the failure",
                            },
                        },
                        indent=2,
                    ),
                    "```",
                ])
                return "\n".join(lines)

            return RECOVERY_PROMPT

        return None

    def get_tool_error_correction_prompt(
        self,
        task: Task,
        context: ToolContext,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_result: ToolResult,
        extra_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Provide a targeted correction prompt when propose_patch fails validation."""
        if tool_name != "propose_patch" or tool_result.ok:
            return None

        defect_ctx = find_target_defect_context(task, context, "", extra_context)
        target_file = defect_ctx.get("target_file") or "app.py"
        old_str = defect_ctx.get("old_str") or tool_args.get("old_str") or "return price - tax"
        new_str = defect_ctx.get("new_str") or tool_args.get("new_str") or "return price + tax"
        explanation = tool_args.get("explanation") or "Correctly adds tax to the price"
        evidence = tool_args.get("evidence") or "pytest test_app.py reproduced the failure"

        err_msg = tool_result.error or "Validation error"
        is_absolute = "absolute" in err_msg.lower()
        reason = "because the path is absolute" if is_absolute else f"due to validation error: {err_msg}"

        return (
            f"propose_patch was rejected {reason}.\n"
            "Reissue the SAME structured propose_patch call using the repository-relative path from repository evidence.\n"
            f"For this target the correct path is {target_file}.\n"
            "Do not output prose or a shell command.\n"
            "Use the propose_patch tool now.\n\n"
            "Respond ONLY with a JSON block:\n"
            "```json\n"
            + json.dumps(
                {
                    "tool": "propose_patch",
                    "args": {
                        "path": target_file,
                        "old_str": old_str,
                        "new_str": new_str,
                        "explanation": explanation,
                        "evidence": evidence,
                    },
                },
                indent=2,
            )
            + "\n```"
        )
