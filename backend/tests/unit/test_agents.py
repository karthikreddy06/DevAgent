"""Unit tests for agent helpers and tool call extraction."""

from __future__ import annotations

import pytest

from app.agents.base import extract_tool_calls


@pytest.mark.unit
def test_extract_tool_calls() -> None:
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
