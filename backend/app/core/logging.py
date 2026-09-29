"""Structured logging with mandatory secret redaction.

Every log event passes through the redaction processor, so an accidental
``logger.info("cfg=%r", settings)`` or a provider error that echoes an API key
cannot leak credentials into the log stream.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from typing import Any, cast
from urllib.parse import urlsplit

import structlog
from structlog.typing import EventDict, WrappedLogger

from app.core.config import Settings, get_settings
from app.core.redaction import redact_value, register_secret

_REDACTED_KEYS = {"settings", "config"}


def redaction_processor(logger: WrappedLogger, method_name: str, event_dict: EventDict) -> EventDict:
    """Scrub credentials from a log event before it is rendered."""
    return cast("EventDict", redact_value(dict(event_dict)))


def register_runtime_secrets(settings: Settings) -> None:
    """Teach the redactor the application's own secrets."""
    register_secret(settings.llm_api_key_value)
    register_secret(settings.github_token_value)
    register_secret(settings.jwt_secret_value)
    register_secret(settings.secret_key_value)
    try:
        password = urlsplit(settings.database_url).password
    except ValueError:
        password = None
    register_secret(password)
    with contextlib.suppress(ValueError):
        register_secret(urlsplit(settings.redis_url).password)


def configure_logging(settings: Settings | None = None) -> None:
    """Configure structlog + stdlib logging. Idempotent."""
    resolved = settings or get_settings()
    register_runtime_secrets(resolved)
    level = getattr(logging, resolved.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for noisy in ("uvicorn.access", "httpx", "httpcore", "docker", "asyncio", "urllib3"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        redaction_processor,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if resolved.log_format == "json"
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger for ``name`` (usually ``__name__``)."""
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))


def bind_context(**values: Any) -> None:
    """Bind request/task scoped context (trace_id, task_id, user_id, ...)."""
    structlog.contextvars.bind_contextvars(**values)


def clear_context() -> None:
    """Clear bound context (called at the end of a request or job)."""
    structlog.contextvars.clear_contextvars()
