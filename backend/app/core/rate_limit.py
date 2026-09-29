"""Redis-backed fixed-window rate limiting.

Rate limiting is defence in depth, not the primary control: when Redis is
unavailable the limiter *fails open* (logs a warning and allows the request) so
that a Redis outage cannot take the API down. This trade-off is intentional and
recorded in docs/threat-model.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.errors import RateLimitedError
from app.core.logging import get_logger

logger = get_logger(__name__)


class RedisCounter(Protocol):
    """Minimal Redis surface the limiter needs (easy to fake in tests)."""

    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> bool: ...

    async def ttl(self, key: str) -> int: ...


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    """Counts requests per subject inside a fixed window."""

    def __init__(
        self,
        counter: RedisCounter | None,
        *,
        limit: int,
        window_seconds: int = 60,
        prefix: str = "devagent:rl",
        enabled: bool = True,
        scope: str = "api",
    ) -> None:
        self._counter = counter
        self._limit = limit
        self._window_seconds = window_seconds
        self._prefix = prefix
        self._enabled = enabled and counter is not None
        self._scope = scope

    @classmethod
    def from_settings(
        cls,
        counter: RedisCounter | None,
        settings: Settings | None = None,
        *,
        scope: str = "api",
    ) -> RateLimiter:
        resolved = settings or get_settings()
        limit = resolved.auth_rate_limit_per_minute if scope == "auth" else resolved.rate_limit_requests_per_minute
        return cls(
            counter,
            limit=limit,
            window_seconds=60,
            enabled=resolved.rate_limit_enabled,
            scope=scope,
        )

    async def check(self, subject: str) -> RateLimitResult:
        if not self._enabled or self._counter is None:
            return RateLimitResult(True, self._limit, self._limit, 0)

        key = f"{self._prefix}:{self._scope}:{subject}"
        try:
            count = await self._counter.incr(key)
            if count == 1:
                await self._counter.expire(key, self._window_seconds)
            if count > self._limit:
                ttl = await self._counter.ttl(key)
                return RateLimitResult(False, self._limit, 0, ttl if ttl > 0 else self._window_seconds)
            return RateLimitResult(True, self._limit, max(0, self._limit - count), 0)
        except Exception as exc:
            logger.warning("rate_limit_backend_unavailable", scope=self._scope, error=type(exc).__name__)
            return RateLimitResult(True, self._limit, self._limit, 0)

    async def enforce(self, subject: str) -> None:
        """Raise :class:`RateLimitedError` when the subject is over budget."""
        result = await self.check(subject)
        if not result.allowed:
            raise RateLimitedError(
                "Too many requests",
                details={"retry_after_seconds": result.retry_after_seconds, "limit": result.limit},
                retryable=True,
            )
