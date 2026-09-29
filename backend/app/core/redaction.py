"""Redaction of secrets from anything that is logged, streamed, persisted or
sent to an LLM provider.

Every log adapter, every SSE payload and every tool result passes through this
module. Two layers are combined:

1. key-name heuristics (``password``, ``token``, ``authorization`` ...)
2. value patterns for well-known credential shapes (API keys, PATs, JWTs,
   private key blocks, credentialed connection strings)

Runtime secrets (the application's own provider keys, git tokens, ...) are
registered with :func:`register_secret` at startup so they are scrubbed
verbatim even if they appear inside free-form text such as a stack trace.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

REDACTED: Final[str] = "***REDACTED***"

_SENSITIVE_KEY_HINTS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "credential",
    "private_key",
    "access_key",
    "client_secret",
    "cookie",
    "session",
    "signature",
    "bearer",
    "database_url",
    "redis_url",
    "dsn",
)

_PATTERN_RULES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github_fine_grained", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\b")),
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    ),
    (
        "credentialed_url",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|redis|mongodb|amqp|https?)(?:\+\w+)?://[^/\s:@]+:[^/\s@]+@"),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret|private[_-]?key)\b"
            r"(\s*[:=]\s*)['\"]?([^\s'\",;]{6,})"
        ),
    ),
)

_MIN_REGISTERED_SECRET_LENGTH: Final[int] = 8
_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a runtime secret so it is scrubbed from all future output."""
    if value and len(value) >= _MIN_REGISTERED_SECRET_LENGTH:
        _registered_secrets.add(value)


def _registered_pattern() -> re.Pattern[str] | None:
    if not _registered_secrets:
        return None
    ordered = sorted(_registered_secrets, key=len, reverse=True)
    return re.compile("|".join(re.escape(item) for item in ordered))


def is_sensitive_key(key: str) -> bool:
    """Return True when a mapping key looks like it holds a credential."""
    lowered = key.lower()
    return any(hint in lowered for hint in _SENSITIVE_KEY_HINTS)


def redact_text(text: str) -> str:
    """Replace every credential-looking substring in ``text``.

    Registered runtime secrets are replaced first (they are the highest signal),
    then the well-known credential patterns.
    """
    if not text:
        return text
    result = text
    registered = _registered_pattern()
    if registered is not None:
        result = registered.sub(REDACTED, result)
    for _name, pattern in _PATTERN_RULES:
        if pattern.groups >= 3:
            # Keep the key name and separator, hide the value.
            result = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", result)
        else:
            result = pattern.sub(REDACTED, result)
    return result


def redact_value(value: Any, *, depth: int = 0) -> Any:
    """Recursively redact a JSON-like structure, returning a new object."""
    if depth > 12:
        return "<max-depth>"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            str(key): (REDACTED if is_sensitive_key(str(key)) else redact_value(item, depth=depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item, depth=depth + 1) for item in value]
    return value


def truncate_text(text: str, limit: int, *, marker: str = "\n...[truncated]") -> str:
    """Middle-truncate ``text`` to at most ``limit`` characters."""
    if limit <= 0 or len(text) <= limit:
        return text
    keep = max(0, (limit - len(marker)) // 2)
    return f"{text[:keep]}{marker}{text[-keep:]}"
