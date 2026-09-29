"""Anthropic chat provider (Messages API, plain HTTP).

Anthropic has no embeddings endpoint, so :class:`AnthropicChatProvider` is chat
only; the embedding provider is selected independently in the factory.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.llm.base import LLMMessage, LLMProvider, LLMResponse, LLMUsage, ResponseFormat
from app.llm.http_client import post_json

DEFAULT_BASE_URL = "https://api.anthropic.com"
API_VERSION = "2023-06-01"
_JSON_INSTRUCTION = (
    "\n\nRespond with a single valid JSON object and nothing else. "
    "Do not wrap it in markdown fences and do not add commentary."
)


class AnthropicChatProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        if not api_key:
            raise ProviderError("LLM_API_KEY is not configured for the anthropic provider")
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_format: ResponseFormat,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        system_parts = [message.content for message in messages if message.role == "system"]
        conversation = [
            {"role": "assistant" if message.role == "assistant" else "user", "content": message.content}
            for message in messages
            if message.role != "system"
        ]
        if response_format == "json":
            system_parts.append(_JSON_INSTRUCTION)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "messages": conversation,
            "stream": stream,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        return payload

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_format: ResponseFormat = "text",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        data = await post_json(
            self._client,
            f"{self._base_url}/v1/messages",
            payload=self._payload(
                messages,
                response_format=response_format,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            ),
            headers=self._headers(),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            provider=self.name,
        )
        blocks = data.get("content")
        if not isinstance(blocks, list):
            raise ProviderError("anthropic returned an unexpected response shape")
        text = "".join(str(block.get("text", "")) for block in blocks if isinstance(block, dict))
        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(usage.get("input_tokens", 0)),
                completion_tokens=int(usage.get("output_tokens", 0)),
            ),
            finish_reason=data.get("stop_reason"),
        )

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(
            messages, response_format="text", temperature=temperature, max_tokens=max_tokens, stream=True
        )
        try:
            async with self._client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                json=payload,
                headers=self._headers(),
                timeout=self.timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        "anthropic streaming request failed",
                        details={"status": response.status_code},
                        retryable=True,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk:
                        continue
                    try:
                        parsed = json.loads(chunk)
                    except ValueError:
                        continue
                    if parsed.get("type") == "content_block_delta":
                        text = (parsed.get("delta") or {}).get("text")
                        if text:
                            yield str(text)
        except httpx.HTTPError as exc:
            raise ProviderError("anthropic streaming failed", details={"reason": type(exc).__name__}) from exc

    async def aclose(self) -> None:
        await self._client.aclose()
