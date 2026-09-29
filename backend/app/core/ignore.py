"""Ignore rules for repository discovery (a documented subset of .gitignore).

Supported syntax: comments, blank lines, negation (``!pattern``), directory
patterns (``dir/``), glob patterns (``*.pyc``), ``**`` style recursion handled by
``fnmatch``'s ``*`` across segments, and anchored patterns (``/build``).

In addition to ``.gitignore`` and ``.devagentignore``, a hard-coded list of
never-indexed paths is always applied: VCS metadata, dependency caches, virtual
environments, build output, and anything that typically holds credentials. The
last group matters for the RAG pipeline - secrets must never be embedded or sent
to an LLM provider.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Final

ALWAYS_IGNORED_DIRS: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".gradle",
        ".m2",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "target",
        "out",
        "bin",
        "obj",
        "coverage",
        "htmlcov",
        ".next",
        ".nuxt",
        ".cache",
        "vendor",
        ".terraform",
    }
)

ALWAYS_IGNORED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".war",
    ".o",
    ".obj",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".bin",
    ".img",
    ".iso",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".rar",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".svgz",
    ".mp3",
    ".mp4",
    ".mov",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".sqlite",
    ".db",
    ".lock",
    ".min.js",
    ".min.css",
    ".map",
    ".pkl",
    ".pickle",
    ".joblib",
    ".pt",
    ".pth",
    ".h5",
    ".onnx",
    ".parquet",
    ".feather",
    ".npy",
    ".npz",
)

# Never read, never index, never send to an LLM provider.
SECRET_FILE_PATTERNS: Final[tuple[str, ...]] = (
    ".env",
    ".env.*",
    "*.env",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "credentials",
    "credentials.json",
    "secrets.yml",
    "secrets.yaml",
    "secrets.json",
    "*.kdbx",
    ".htpasswd",
    "service-account*.json",
)

ALWAYS_IGNORED_FILES: Final[frozenset[str]] = frozenset({".DS_Store", "Thumbs.db"})


@dataclass(frozen=True, slots=True)
class IgnoreRule:
    """A single compiled pattern."""

    pattern: str
    negated: bool = False
    directory_only: bool = False
    anchored: bool = False

    def matches(self, relative_path: str, *, is_dir: bool) -> bool:
        path = relative_path.strip("/")
        prefix = self.pattern.rstrip("/")
        if self.directory_only and not is_dir:
            # A directory-only rule still hides everything inside that directory.
            return path.startswith(prefix + "/")
        if self.anchored or "/" in self.pattern:
            return fnmatch.fnmatchcase(path, self.pattern) or path.startswith(prefix + "/")
        # Unanchored single-segment pattern: match any path segment.
        return any(fnmatch.fnmatchcase(segment, self.pattern) for segment in path.split("/"))


@dataclass(slots=True)
class IgnoreMatcher:
    """Evaluates ignore rules for repository-relative POSIX paths."""

    rules: list[IgnoreRule] = field(default_factory=list)

    @classmethod
    def from_lines(cls, lines: Iterable[str]) -> IgnoreMatcher:
        rules: list[IgnoreRule] = []
        for raw in lines:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            negated = line.startswith("!")
            pattern = (line[1:] if negated else line).strip()
            if not pattern:
                continue
            anchored = pattern.startswith("/")
            directory_only = pattern.endswith("/")
            pattern = pattern.strip("/")
            if not pattern:
                continue
            rules.append(IgnoreRule(pattern=pattern, negated=negated, directory_only=directory_only, anchored=anchored))
        return cls(rules=rules)

    @staticmethod
    def _hard_ignored(parts: tuple[str, ...], *, is_dir: bool, name: str) -> str | None:
        relevant = parts if is_dir else parts[:-1]
        if any(part in ALWAYS_IGNORED_DIRS for part in relevant):
            return "vcs/dependency/build directory"
        if is_dir and name in ALWAYS_IGNORED_DIRS:
            return "vcs/dependency/build directory"
        if not is_dir and name in ALWAYS_IGNORED_FILES:
            return "operating system metadata file"
        if not is_dir and any(name.endswith(suffix) for suffix in ALWAYS_IGNORED_SUFFIXES):
            return "binary or generated artifact"
        if not is_dir and any(fnmatch.fnmatchcase(name, pattern) for pattern in SECRET_FILE_PATTERNS):
            return "potential credential file"
        return None

    def is_ignored(self, relative_path: str, *, is_dir: bool = False) -> bool:
        return self.reason(relative_path, is_dir=is_dir) is not None

    def reason(self, relative_path: str, *, is_dir: bool = False) -> str | None:
        """Explain why a path is ignored (used by the UI and by tests)."""
        path = relative_path.replace("\\", "/").strip("/")
        if not path:
            return None
        parts = PurePosixPath(path).parts
        name = parts[-1] if parts else path

        hard = self._hard_ignored(parts, is_dir=is_dir, name=name)
        if hard is not None:
            return hard

        ignored = False
        for rule in self.rules:
            if rule.matches(path, is_dir=is_dir):
                ignored = not rule.negated
        return "gitignore rule" if ignored else None

    def allowed(self, relative_path: str, *, is_dir: bool = False) -> bool:
        return self.reason(relative_path, is_dir=is_dir) is None


def load_ignore_matcher(root: Path, *, extra_patterns: Iterable[str] = ()) -> IgnoreMatcher:
    """Build a matcher from ``.gitignore``, ``.devagentignore`` and extra lines."""
    lines: list[str] = list(extra_patterns)
    for name in (".gitignore", ".devagentignore"):
        candidate = root / name
        if candidate.is_file():
            try:
                lines.extend(candidate.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:  # pragma: no cover - an unreadable ignore file is not fatal
                continue
    return IgnoreMatcher.from_lines(lines)
