"""Identifier helpers.

DevAgent uses UUIDv7 for primary keys: the high bits are a millisecond
timestamp so indexes stay local on insert (unlike UUIDv4) while the random tail
keeps them unguessable. Planned/reviewed as ADR-0007.
"""

from __future__ import annotations

import re
import secrets
import time
import uuid
from typing import Final

_SLUG_INVALID: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


def uuid7() -> uuid.UUID:
    """Generate a time-ordered (UUIDv7) identifier."""
    timestamp_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0x2 << 62) | rand_b
    return uuid.UUID(int=value)


def new_id() -> uuid.UUID:
    """Alias used by models and services."""
    return uuid7()


def slugify(value: str, *, max_length: int = 48, fallback: str = "repo") -> str:
    """Turn arbitrary text (e.g. a repository name) into a safe slug."""
    lowered = _SLUG_INVALID.sub("-", value.strip().lower()).strip("-")
    if not lowered:
        lowered = fallback
    return lowered[:max_length].strip("-") or fallback


def short_hex(length: int = 8) -> str:
    """Random hex suffix, e.g. for workspace directory names."""
    return secrets.token_hex(max(1, length // 2 + 1))[:length]
