"""Filesystem layout and path-traversal-safe helpers.

All repository and task data lives under ``WORKSPACES_DIR``. Every path that
originates from user input, a tool call, or repository content goes through
:func:`normalize_relative_path` / :func:`safe_join` / :func:`ensure_within`, so
an agent (or a malicious repository) cannot read or write outside its own
workspace.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

from app.core.config import Settings, get_settings
from app.core.errors import PolicyViolationError, ValidationError

_DRIVE_PREFIX: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:")
_COPY_IGNORE: Final[tuple[str, ...]] = ("__pycache__", ".pytest_cache", ".mypy_cache", "node_modules", ".venv")


def normalize_relative_path(value: str) -> str:
    """Validate and normalise a repository-relative POSIX path.

    Rejects absolute paths, drive letters, parent-directory segments, NUL bytes
    and empty input. Backslashes are accepted as separators (Windows clients)
    and folded to POSIX form so a path means the same thing everywhere.
    """
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        raise ValidationError("A file path is required")
    if "\x00" in raw:
        raise ValidationError("Path contains an illegal character")
    if raw.startswith("/") or _DRIVE_PREFIX.match(raw):
        raise ValidationError("Absolute paths are not allowed")
    parts = [part for part in PurePosixPath(raw).parts if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValidationError("Path traversal is not allowed", details={"path": value})
    if not parts:
        raise ValidationError("A file path is required")
    return "/".join(parts)


def ensure_within(base: Path, candidate: Path) -> Path:
    """Resolve ``candidate`` and assert it stays inside ``base``."""
    base_resolved = base.resolve()
    candidate_resolved = Path(candidate).resolve()
    if candidate_resolved != base_resolved and base_resolved not in candidate_resolved.parents:
        raise PolicyViolationError(
            "Path escapes the permitted workspace root",
            details={"base": str(base_resolved), "candidate": str(candidate_resolved)},
        )
    return candidate_resolved


def safe_join(base: Path, relative: str) -> Path:
    """Join a validated relative path onto ``base``, then re-verify containment."""
    return ensure_within(base, base / normalize_relative_path(relative))


def looks_binary(data: bytes) -> bool:
    """Heuristic binary detection used by indexing and file reads."""
    if not data:
        return False
    if b"\x00" in data[:4096]:
        return True
    sample = data[:4096]
    text_chars = sum(1 for byte in sample if byte in b"\n\r\t\f\b" or 32 <= byte < 127)
    return (text_chars / len(sample)) < 0.85


@dataclass(frozen=True, slots=True)
class WorkspaceManager:
    """Owns the on-disk layout for clones and per-task working copies."""

    root: Path

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> WorkspaceManager:
        resolved = settings or get_settings()
        return cls(root=resolved.workspaces_dir.resolve())

    # ------------------------------------------------------------- locations
    @property
    def repositories_dir(self) -> Path:
        return self.root / "repos"

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    def repository_dir(self, repository_id: str) -> Path:
        return ensure_within(self.root, self.repositories_dir / repository_id)

    def task_dir(self, repository_id: str, task_id: str) -> Path:
        return ensure_within(self.root, self.tasks_dir / repository_id / task_id)

    def task_repo_dir(self, repository_id: str, task_id: str) -> Path:
        """The working copy that is mounted into the sandbox at /workspace."""
        return self.task_dir(repository_id, task_id) / "repo"

    # ------------------------------------------------------------ operations
    def ensure_repository_dir(self, repository_id: str) -> Path:
        path = self.repository_dir(repository_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def prepare_task_workspace(self, repository_id: str, task_id: str) -> Path:
        """Copy the canonical clone into an isolated per-task working copy.

        Agents can only ever mutate this copy, so a bad proposal or a crashing
        test run cannot damage the canonical clone.
        """
        source = self.repository_dir(repository_id)
        if not source.exists():
            raise PolicyViolationError("Repository clone not found", details={"repository_id": repository_id})
        destination = self.task_repo_dir(repository_id, task_id)
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(*_COPY_IGNORE), symlinks=False)
        return destination

    def remove_task_workspace(self, repository_id: str, task_id: str) -> None:
        shutil.rmtree(self.task_dir(repository_id, task_id), ignore_errors=True)

    def remove_repository(self, repository_id: str) -> None:
        shutil.rmtree(self.repository_dir(repository_id), ignore_errors=True)

    def directory_size_bytes(self, path: Path) -> int:
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
        return total

    # -------------------------------------------------------------------- io
    @staticmethod
    def read_text(path: Path, *, max_bytes: int = 400_000) -> str:
        data = path.read_bytes()
        if len(data) > max_bytes:
            raise ValidationError("File is too large to read", details={"max_bytes": max_bytes})
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def write_text(path: Path, content: str) -> Path:
        """Write atomically (temp file + replace) so a crash cannot truncate."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".devagent-tmp")
        temporary.write_text(content, encoding="utf-8", newline="")
        temporary.replace(path)
        return path
