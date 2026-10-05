"""Unit tests for pre-approval proposal validator."""

from __future__ import annotations

import difflib
from pathlib import Path

import pytest

from app.models.enums import ChangeType
from app.orchestration.proposal_validator import (
    validate_patch_in_temp_workspace,
    validate_patch_paths_safe,
    validate_patch_structure,
    validate_proposal_before_approval,
    validate_proposal_persistable,
)


@pytest.mark.unit
def test_validate_patch_structure() -> None:
    # Non-dict
    ok, err = validate_patch_structure("not a dict")  # type: ignore[arg-type]
    assert not ok
    assert "dictionary" in err

    # Missing path in single file
    ok, err = validate_patch_structure({})
    assert not ok
    assert "path" in err

    # Empty files list
    ok, err = validate_patch_structure({"files": []})
    assert not ok
    assert "non-empty" in err

    # Valid single file
    ok, _ = validate_patch_structure({"path": "src/calculator.py"})
    assert ok

    # Valid multiple files
    ok, _ = validate_patch_structure({"files": [{"path": "src/a.py"}, {"path": "src/b.py"}]})
    assert ok


@pytest.mark.unit
def test_validate_patch_paths_safe(temp_workspace: Path) -> None:
    # Safe path
    ok, _ = validate_patch_paths_safe({"path": "src/calculator.py"}, temp_workspace)
    assert ok

    # Traversal path
    ok, err = validate_patch_paths_safe({"path": "../outside.py"}, temp_workspace)
    assert not ok
    assert "Unsafe" in err

    # Absolute path
    ok, err = validate_patch_paths_safe({"path": "/etc/passwd"}, temp_workspace)
    assert not ok
    assert "Unsafe" in err


@pytest.mark.unit
def test_validate_patch_in_temp_workspace_clean_modify(temp_workspace: Path) -> None:
    calc = temp_workspace / "src" / "calculator.py"
    calc_content = calc.read_text(encoding="utf-8")

    old_str = "return a + b"
    new_str = "return a + b  # Optimized"
    diff = "".join(
        difflib.unified_diff(
            calc_content.splitlines(keepends=True),
            calc_content.replace(old_str, new_str).splitlines(keepends=True),
            fromfile="a/src/calculator.py",
            tofile="b/src/calculator.py",
        )
    )

    patch_data = {
        "path": "src/calculator.py",
        "old_str": old_str,
        "new_str": new_str,
        "unified_diff": diff,
    }

    ok, msg = validate_patch_in_temp_workspace(temp_workspace, patch_data)
    assert ok is True
    assert "validated successfully" in msg
    # Crucial: verify that the real workspace was NOT modified
    assert "Optimized" not in calc.read_text(encoding="utf-8")


@pytest.mark.unit
def test_validate_patch_in_temp_workspace_syntax_error(temp_workspace: Path) -> None:
    old_str = "return a + b"
    new_str = "return a + (("  # Syntax error

    patch_data = {
        "path": "src/calculator.py",
        "old_str": old_str,
        "new_str": new_str,
        "unified_diff": "dummy diff",
    }

    ok, msg = validate_patch_in_temp_workspace(temp_workspace, patch_data)
    assert ok is False
    assert "Syntax error" in msg


@pytest.mark.unit
def test_validate_patch_in_temp_workspace_new_file(temp_workspace: Path) -> None:
    patch_data = {
        "files": [
            {
                "path": "tests/test_new.py",
                "change_type": ChangeType.ADD,
                "proposed_content": "def test_something():\n    assert 1 == 1\n",
                "unified_diff": "diff --git a/dev/null b/tests/test_new.py",
            }
        ],
        "unified_diff": "diff --git a/dev/null b/tests/test_new.py",
    }

    ok, _ = validate_proposal_before_approval(temp_workspace, patch_data)
    assert ok is True
    # Real workspace must remain untouched
    assert not (temp_workspace / "tests" / "test_new.py").exists()


@pytest.mark.unit
def test_validate_patch_old_str_not_found(temp_workspace: Path) -> None:
    patch_data = {
        "path": "src/calculator.py",
        "old_str": "non_existent_function_call()",
        "new_str": "replacement()",
        "unified_diff": "dummy",
    }
    ok, msg = validate_patch_in_temp_workspace(temp_workspace, patch_data)
    assert ok is False
    assert "not found" in msg


@pytest.mark.unit
def test_validate_proposal_persistable() -> None:
    ok, err = validate_proposal_persistable({"unified_diff": ""})
    assert not ok
    assert "unified diff" in err

    ok, _ = validate_proposal_persistable({"unified_diff": "diff content", "path": "src/a.py"})
    assert ok
