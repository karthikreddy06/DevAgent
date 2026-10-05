"""Unit tests for agent helpers, tool call extraction, deduplication, and budget isolation."""

from __future__ import annotations

import pytest

from app.agents.base import extract_tool_calls
from app.core.config import Settings
from app.core.errors import BudgetExhaustedError
from app.orchestration.budgets import BudgetTracker


@pytest.mark.unit
def test_extract_tool_calls_basic() -> None:
    # 1. Markdown JSON block
    text1 = (
        'I need to read the file first.\n```json\n{\n  "tool": "read_file",\n  "args": {"path": "src/app.py"}\n}\n```\n'
    )
    calls1 = extract_tool_calls(text1)
    assert len(calls1) == 1
    assert calls1[0]["tool"] == "read_file"
    assert calls1[0]["args"]["path"] == "src/app.py"

    # 2. Raw JSON format
    text2 = 'Let us check: {"tool": "list_files", "args": {"path": "."}}'
    calls2 = extract_tool_calls(text2)
    assert len(calls2) == 1
    assert calls2[0]["tool"] == "list_files"

    # 3. No tool call
    text3 = "This is a plain explanation without tool calls."
    calls3 = extract_tool_calls(text3)
    assert len(calls3) == 0


@pytest.mark.unit
def test_extract_tool_calls_deduplication() -> None:
    """Verifies that identical tool calls with identical arguments in a single turn are deduplicated."""
    # 18 identical git_status calls and 6 identical search_codebase calls
    blocks = []
    blocks.append('```json\n{"tool": "list_files", "args": {"path": "."}}\n```')
    for _ in range(6):
        blocks.append('```json\n{"tool": "search_codebase", "args": {"query": "test_bug", "top_k": 8}}\n```')
    for _ in range(18):
        blocks.append('```json\n{"tool": "git_status", "args": {"short": true}}\n```')

    full_text = "\n".join(blocks)
    calls = extract_tool_calls(full_text)

    # All duplicates are stripped: only 3 unique calls survive
    assert len(calls) == 3
    tool_names = [c["tool"] for c in calls]
    assert tool_names == ["list_files", "search_codebase", "git_status"]


@pytest.mark.unit
def test_extract_tool_calls_per_turn_cap() -> None:
    """Verifies that max_per_turn bounds the number of extracted calls."""
    blocks = []
    for i in range(10):
        blocks.append(f'```json\n{{"tool": "read_file", "args": {{"path": "file_{i}.py"}}}}\n```')

    full_text = "\n".join(blocks)
    # With max_per_turn=4
    calls = extract_tool_calls(full_text, max_per_turn=4)
    assert len(calls) == 4
    assert calls[0]["args"]["path"] == "file_0.py"
    assert calls[3]["args"]["path"] == "file_3.py"

    # Without cap
    all_calls = extract_tool_calls(full_text, max_per_turn=None)
    assert len(all_calls) == 10


@pytest.mark.unit
def test_extract_tool_calls_malformed_blocks() -> None:
    """Verifies that malformed JSON or empty tool names are ignored without throwing exceptions."""
    text = (
        '```json\n{"not_a_tool": "test"}\n```\n'
        '```json\n{"tool": "", "args": {}}\n```\n'
        '```json\n{"tool": 12345}\n```\n'
        "```json\nINVALID JSON BLOCK {}}\n```\n"
        '```json\n{"tool": "valid_tool", "args": {"key": "val"}}\n```\n'
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["tool"] == "valid_tool"
    assert calls[0]["args"] == {"key": "val"}


@pytest.mark.unit
def test_stage_aware_budget_tracker() -> None:
    """Verifies stage-level tool call isolation, stage budget checks, and global limits."""
    settings = Settings(
        agent_max_steps=18,
        agent_max_tool_calls=30,
        agent_max_tokens=150_000,
        agent_timeout_seconds=900,
    )
    budget = BudgetTracker.from_settings(settings)

    # 1. Start PLANNING stage with 2 max tool calls
    budget.start_stage("PLANNING", max_steps=3, max_tool_calls=2)
    assert budget.record_tool_call() is True
    assert budget.record_tool_call() is True
    # 3rd call in PLANNING stage hits stage limit -> returns False gracefully
    assert budget.record_tool_call() is False

    # 2. Start ANALYZING stage with 3 max tool calls
    budget.start_stage("ANALYZING", max_steps=4, max_tool_calls=3)
    assert budget.record_tool_call() is True
    assert budget.record_tool_call() is True
    assert budget.record_tool_call() is True
    # 4th call in ANALYZING stage hits stage limit
    assert budget.record_tool_call() is False

    # Global tool calls should be 5 (2 from PLANNING + 3 from ANALYZING)
    assert budget.tool_calls == 5

    # 3. Global tool limit enforcement
    small_budget = BudgetTracker(max_steps=10, max_tool_calls=2)
    small_budget.start_stage("TEST", max_steps=5, max_tool_calls=5)
    assert small_budget.record_tool_call() is True
    assert small_budget.record_tool_call() is True
    # 3rd call exceeds global limit of 2 -> raises BudgetExhaustedError
    with pytest.raises(BudgetExhaustedError) as exc_info:
        small_budget.record_tool_call()
    assert "Agent tool call budget exhausted" in str(exc_info.value)
