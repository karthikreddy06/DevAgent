"""Pre-approval validation for proposed patches.

Validates that a proposed patch has safe paths, a valid structure, applies
cleanly in an isolated temporary copy of the workspace, has syntactically
valid files, and can be properly persisted before moving to AWAITING_APPROVAL.
"""

from __future__ import annotations

import difflib
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

from app.core.errors import PolicyViolationError, ValidationError
from app.core.logging import get_logger
from app.core.paths import normalize_relative_path, safe_join
from app.models.enums import ChangeType

logger = get_logger(__name__)

_COPY_IGNORE_PATTERNS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    ".git",
)


def validate_patch_structure(patch_data: dict[str, Any]) -> tuple[bool, str]:
    """Verify that patch_data conforms to the expected dictionary schema."""
    if not isinstance(patch_data, dict):
        return False, "Patch data must be a dictionary"

    files = patch_data.get("files")
    if files is not None:
        if not isinstance(files, list) or len(files) == 0:
            return False, "Patch 'files' must be a non-empty list"
        for idx, f in enumerate(files):
            if not isinstance(f, dict):
                return False, f"File change item at index {idx} must be a dictionary"
            if not f.get("path") or not isinstance(f["path"], str):
                return False, f"File change item at index {idx} is missing a valid 'path'"
    else:
        if not patch_data.get("path") or not isinstance(patch_data["path"], str):
            return False, "Patch data is missing a valid 'path'"

    return True, "Structure is valid"


def validate_patch_paths_safe(patch_data: dict[str, Any], workspace: Path) -> tuple[bool, str]:
    """Verify that all paths are safe, relative, and stay within the workspace."""
    files = patch_data.get("files") or [patch_data]
    for f in files:
        rel_path = f.get("path", "")
        try:
            norm = normalize_relative_path(rel_path)
            safe_join(workspace, norm)
        except (ValidationError, PolicyViolationError) as exc:
            return False, f"Unsafe file path '{rel_path}': {exc}"
    return True, "All paths are safe"


def validate_patch_in_temp_workspace(workspace: Path, patch_data: dict[str, Any]) -> tuple[bool, str]:
    """Apply the patch in an isolated temporary copy of the workspace.

    Verifies:
    1. Structure and path safety.
    2. Patch applies cleanly (old_str matches uniquely for modifications).
    3. New files do not conflict and are successfully created.
    4. Modified and new Python files compile with valid syntax.
    """
    struct_ok, struct_err = validate_patch_structure(patch_data)
    if not struct_ok:
        return False, f"Patch structure invalid: {struct_err}"

    paths_ok, paths_err = validate_patch_paths_safe(patch_data, workspace)
    if not paths_ok:
        return False, f"Patch path safety check failed: {paths_err}"

    files = patch_data.get("files") or [patch_data]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_workspace = Path(temp_dir) / "workspace"
        try:
            shutil.copytree(
                workspace,
                temp_workspace,
                symlinks=False,
                ignore=shutil.ignore_patterns(*_COPY_IGNORE_PATTERNS),
            )
        except OSError as exc:
            return False, f"Failed to prepare temporary workspace copy: {exc}"

        for f in files:
            rel_path = f["path"]
            try:
                target = safe_join(temp_workspace, rel_path)
            except (ValidationError, PolicyViolationError) as exc:
                return False, f"Path escape in temporary workspace for '{rel_path}': {exc}"

            raw_change_type = f.get("change_type", ChangeType.MODIFY)
            is_new = (
                raw_change_type in ("add", ChangeType.ADD)
                or f.get("is_new_file", False)
                or (not target.exists() and not f.get("old_str"))
            )

            if is_new:
                content = f.get("proposed_content", f.get("new_str"))
                if content is None:
                    return False, f"New file '{rel_path}' has no proposed content"
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                except OSError as exc:
                    return False, f"Failed to write new file '{rel_path}': {exc}"

                # Syntax check for Python files
                if rel_path.endswith(".py"):
                    try:
                        compile(content, rel_path, "exec")
                    except SyntaxError as exc:
                        return False, f"Syntax error in new file '{rel_path}': {exc}"

            else:
                if not target.is_file():
                    return False, f"Target file to modify does not exist: '{rel_path}'"

                content = target.read_text(encoding="utf-8", errors="replace")
                old_str = f.get("old_str")
                new_str = f.get("new_str")

                if old_str is not None and new_str is not None:
                    count = content.count(old_str)
                    if count == 0:
                        return False, f"old_str not found in target file: '{rel_path}'"
                    if count > 1:
                        return False, f"old_str occurs {count} times in '{rel_path}'; replacement must be unique"
                    new_content = content.replace(old_str, new_str, 1)
                elif f.get("proposed_content") is not None:
                    new_content = f["proposed_content"]
                else:
                    return False, f"No replacement snippet or content provided for '{rel_path}'"

                try:
                    target.write_text(new_content, encoding="utf-8")
                except OSError as exc:
                    return False, f"Failed to apply modifications to '{rel_path}': {exc}"

                # Syntax check for Python files
                if rel_path.endswith(".py"):
                    try:
                        compile(new_content, rel_path, "exec")
                    except SyntaxError as exc:
                        return False, f"Syntax error in modified file '{rel_path}': {exc}"

    return True, "Patch validated successfully in isolated temporary workspace"


def validate_proposal_persistable(patch_data: dict[str, Any]) -> tuple[bool, str]:
    """Verify that the proposal has sufficient information to create database records."""
    unified_diff = patch_data.get("unified_diff")
    if not unified_diff or not isinstance(unified_diff, str) or not unified_diff.strip():
        return False, "Proposal must contain a non-empty unified diff"

    files = patch_data.get("files") or [patch_data]
    for idx, f in enumerate(files):
        if not f.get("path"):
            return False, f"ChangeFile at index {idx} missing path"
    return True, "Proposal can be persisted"


def validate_proposal_before_approval(
    workspace: Path, patch_data: dict[str, Any]
) -> tuple[bool, str]:
    """End-to-end pre-approval patch validation gate."""
    # 1. Structure
    ok, err = validate_patch_structure(patch_data)
    if not ok:
        return False, err

    # 2. Persistence capability
    ok, err = validate_proposal_persistable(patch_data)
    if not ok:
        return False, err

    # 3. Clean application and syntax check in temporary copy
    ok, err = validate_patch_in_temp_workspace(workspace, patch_data)
    if not ok:
        return False, err

    return True, "Proposed patch passed all pre-approval validation checks"
