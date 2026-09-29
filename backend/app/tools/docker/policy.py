"""Command policy for the sandbox.

Layer 1 of execution control. The **primary** control is isolation (network off,
read-only rootfs, dropped capabilities, non-root user, resource limits) - this
module is defence in depth and exists so that obviously dangerous invocations
never even reach the daemon.

Rules enforced here:

* argv is a list of strings - ``shell=True`` is never used anywhere in DevAgent.
* ``argv[0]`` must be on the allowlist for the detected stack.
* Executables on the deny list are always refused.
* Shell metacharacters, parent-directory segments and absolute paths outside the
  sandbox roots are rejected.
* Argument count/length are bounded.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Final

from app.core.errors import PolicyViolationError

READ_ONLY_UTILITIES: Final[frozenset[str]] = frozenset(
    {"ls", "cat", "head", "tail", "wc", "grep", "find", "file", "pwd", "echo", "sort", "uniq", "diff", "stat"}
)

STACK_EXECUTABLES: Final[dict[str, frozenset[str]]] = {
    "python": frozenset(
        {
            "python",
            "python3",
            "python3.11",
            "python3.12",
            "pytest",
            "py.test",
            "pip",
            "pip3",
            "uv",
            "coverage",
            "mypy",
            "ruff",
            "black",
            "flake8",
            "tox",
        }
    ),
    "javascript": frozenset({"node", "npm", "npx", "yarn", "pnpm", "jest", "vitest", "tsc", "mocha", "eslint"}),
    "java": frozenset({"java", "javac", "mvn", "gradle", "mvnw", "gradlew", "junit"}),
    "go": frozenset({"go", "gofmt", "gotestsum", "go-junit-report"}),
    "cpp": frozenset({"make", "cmake", "g++", "gcc", "clang", "clang++", "ctest", "nm", "ldd", "objdump"}),
}

DENIED_EXECUTABLES: Final[frozenset[str]] = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "ksh",
        "csh",
        "fish",
        "curl",
        "wget",
        "nc",
        "netcat",
        "ncat",
        "telnet",
        "ssh",
        "scp",
        "sftp",
        "rsync",
        "ftp",
        "docker",
        "podman",
        "kubectl",
        "sudo",
        "su",
        "doas",
        "mount",
        "umount",
        "nsenter",
        "unshare",
        "chroot",
        "iptables",
        "systemctl",
        "crontab",
        "reboot",
        "shutdown",
        "kill",
        "pkill",
        "dd",
        "mkfs",
        "fdisk",
        "parted",
        "rm",
        "shred",
        "chown",
        "chmod",
        "chgrp",
        "useradd",
        "usermod",
        "passwd",
        "git",
        "gpg",
        "openssl",
        "env",
        "printenv",
        "base64",
        "xxd",
        "socat",
        "busybox",
    }
)

_SHELL_METACHARACTERS: Final[tuple[str, ...]] = ("&&", "||", ";", "|", ">", "<", "$(", "`", "\n", "${")
_ALLOWED_ABSOLUTE_PREFIXES: Final[tuple[str, ...]] = ("/workspace", "/tmp", "/usr", "/bin", "/sbin", "/lib", "/opt")
_MAX_ARGUMENTS: Final[int] = 64
_MAX_ARGUMENT_LENGTH: Final[int] = 4096


def detect_stack(languages: Sequence[str], *, test_framework: str | None = None) -> str:
    """Choose the command allowlist bucket for a repository."""
    lowered = {language.lower() for language in languages}
    framework = (test_framework or "").lower()
    if framework in {"jest", "vitest", "mocha"}:
        return "javascript"
    if {"python", "python3"} & lowered or framework in {"pytest", "unittest"}:
        return "python"
    if {"typescript", "javascript"} & lowered:
        return "javascript"
    if {"java", "kotlin"} & lowered:
        return "java"
    if "go" in lowered:
        return "go"
    if {"c++", "cpp", "c"} & lowered:
        return "cpp"
    return "python"


def validate_command(argv: Sequence[str], *, stack: str = "python", cwd: str = "/workspace") -> list[str]:
    """Validate and normalise an argv list, or raise :class:`PolicyViolationError`."""
    if not argv:
        raise PolicyViolationError("Empty command")
    if len(argv) > _MAX_ARGUMENTS:
        raise PolicyViolationError("Too many command arguments", details={"count": len(argv)})

    normalized: list[str] = []
    for index, part in enumerate(argv):
        if not isinstance(part, str):
            raise PolicyViolationError("Command arguments must be strings")
        if part and "\x00" in part:
            raise PolicyViolationError("Command argument contains an illegal character")
        if len(part) > _MAX_ARGUMENT_LENGTH:
            raise PolicyViolationError("Command argument is too long", details={"index": index})
        if any(token in part for token in _SHELL_METACHARACTERS):
            raise PolicyViolationError(
                "Command argument contains shell metacharacters, which DevAgent never interprets",
                details={"argument": part[:120]},
            )
        if part.startswith("/") and not part.startswith(_ALLOWED_ABSOLUTE_PREFIXES):
            raise PolicyViolationError(
                "Command argument references a path outside the sandbox workspace",
                details={"argument": part[:200]},
            )
        if ".." in part.split("/"):
            raise PolicyViolationError(
                "Command argument contains a parent-directory segment", details={"argument": part[:120]}
            )
        normalized.append(part)

    executable = os.path.basename(normalized[0])
    if executable in DENIED_EXECUTABLES:
        raise PolicyViolationError("Executable is on the sandbox deny list", details={"executable": executable})

    allowed = STACK_EXECUTABLES.get(stack, STACK_EXECUTABLES["python"]) | READ_ONLY_UTILITIES
    if executable not in allowed:
        raise PolicyViolationError(
            "Executable is not on the allowlist for this stack",
            details={"executable": executable, "stack": stack, "allowed_sample": sorted(allowed)[:12]},
        )

    if not cwd.startswith("/workspace"):
        raise PolicyViolationError("Commands must run inside the mounted workspace", details={"cwd": cwd})

    return normalized


def describe_policy() -> dict[str, object]:
    """Policy summary surfaced in the UI and in the security documentation."""
    return {
        "allow_by_stack": {stack: sorted(executables) for stack, executables in STACK_EXECUTABLES.items()},
        "read_only_utilities": sorted(READ_ONLY_UTILITIES),
        "denied_executables": sorted(DENIED_EXECUTABLES),
        "shell_interpretation": False,
        "max_arguments": _MAX_ARGUMENTS,
    }
