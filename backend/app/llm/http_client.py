"""Shared HTTP helper for LLM providers: timeouts, bounded retries, redacted errors."""

from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.core.redaction import redact_text

RETRYABLE_STATUS: frozenset[int] = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 8.0
_ERROR_BODY_CHARS = 600


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
    max_retries: int,
    provider: str,
) -> dict[str, Any]:
    """POST JSON with exponential backoff and a sanitised error surface.

    The response body is redacted before it is attached to an error, so a
    provider that echoes a key or a credential-bearing URL cannot leak it into
    logs or the UI.
    """
    delay = 0.5
    last_error = "no attempt made"

    for attempt in range(max_retries + 1):
        try:
            response = await client.post(url, json=payload, headers=headers, timeout=timeout_seconds)
        except httpx.TimeoutException:
            last_error = f"timeout after {timeout_seconds:g}s"
            retryable = True
        except httpx.HTTPError as exc:
            last_error = type(exc).__name__
            retryable = True
        else:
            if response.status_code < 400:
                try:
                    data = response.json()
                    if isinstance(data, dict):
                        return data
                    return {"data": data}
                except ValueError as exc:
                    raise ProviderError(
                        f"{provider} returned a non-JSON response",
                        details={"status": response.status_code},
                    ) from exc
            last_error = f"HTTP {response.status_code}: {redact_text(response.text[:_ERROR_BODY_CHARS])}"
            retryable = response.status_code in RETRYABLE_STATUS

        if not retryable or attempt >= max_retries:
            raise ProviderError(
                f"{provider} request failed",
                details={"reason": last_error, "attempts": attempt + 1, "url": _safe_url(url)},
                retryable=retryable,
            )
        await asyncio.sleep(delay + random.uniform(0.0, delay / 4))  # noqa: S311 - jitter only, not security relevant
        delay = min(delay * 2, _MAX_BACKOFF_SECONDS)

    raise ProviderError(f"{provider} request failed", details={"reason": last_error}, retryable=True)


def _safe_url(url: str) -> str:
    """Strip query strings from a URL before it reaches a log or an error."""
    return url.split("?", 1)[0]


def auth_headers(token: str, *, scheme: str = "Bearer") -> dict[str, str]:
    return {"Authorization": f"{scheme} {token}", "Content-Type": "application/json"}
