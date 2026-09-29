"""OpenAI chat + embedding providers (plain HTTP, no vendor SDK).

Using ``httpx`` directly keeps the dependency surface small and makes every
provider a thin, auditable adapter over the same interface.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.core.errors import ProviderError
from app.llm.base import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ResponseFormat,
)
from app.llm.http_client import auth_headers, post_json

DEFAULT_BASE_URL = "https://api.openai.com/v1"
_KNOWN_EMBEDDING_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIChatProvider(LLMProvider):
    name = "openai"

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
            raise ProviderError("LLM_API_KEY is not configured for the openai provider")
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    def _payload(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_format: ResponseFormat,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }
        if response_format == "json":
            payload["response_format"] = {"type": "json_object"}
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
            f"{self._base_url}/chat/completions",
            payload=self._payload(
                messages,
                response_format=response_format,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            ),
            headers=auth_headers(self._api_key),
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            provider=self.name,
        )
        try:
            choice = data["choices"][0]
            text = choice["message"].get("content") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("openai returned an unexpected response shape") from exc
        usage = data.get("usage") or {}
        return LLMResponse(
            text=str(text),
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            finish_reason=choice.get("finish_reason"),
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
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=auth_headers(self._api_key),
                timeout=self.timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        "openai streaming request failed",
                        details={"status": response.status_code},
                        retryable=True,
                    )
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        parsed = json.loads(chunk)
                    except ValueError:
                        continue
                    choices = parsed.get("choices") or []
                    if not choices:
                        continue
                    content = (choices[0].get("delta") or {}).get("content")
                    if content:
                        yield str(content)
        except httpx.HTTPError as exc:
            raise ProviderError("openai streaming failed", details={"reason": type(exc).__name__}) from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dim: int,
        base_url: str | None = None,
        batch_size: int = 64,
        timeout_seconds: float = 120.0,
    ) -> None:
        super().__init__(model=model, dim=dim, batch_size=batch_size, timeout_seconds=timeout_seconds)
        if not api_key:
            raise ProviderError("LLM_API_KEY is not configured for the openai embedding provider")
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self.model, provider=self.name, dim=self.dim)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            payload: dict[str, Any] = {"model": self.model, "input": batch}
            known_dim = _KNOWN_EMBEDDING_DIMS.get(self.model)
            if known_dim is not None and known_dim != self.dim:
                payload["dimensions"] = self.dim
            data = await post_json(
                self._client,
                f"{self._base_url}/embeddings",
                payload=payload,
                headers=auth_headers(self._api_key),
                timeout_seconds=self.timeout_seconds,
                max_retries=2,
                provider=self.name,
            )
            items = data.get("data")
            if not isinstance(items, list) or len(items) != len(batch):
                raise ProviderError("openai returned an unexpected embedding response")
            ordered = sorted(items, key=lambda item: int(item.get("index", 0)))
            vectors.extend([[float(value) for value in item["embedding"]] for item in ordered])
        self._validate_dims(vectors)
        return EmbeddingResult(vectors=vectors, model=self.model, provider=self.name, dim=self.dim)

    def _validate_dims(self, vectors: list[list[float]]) -> None:
        for vector in vectors:
            if len(vector) != self.dim:
                raise ProviderError(
                    "Embedding dimension mismatch",
                    details={"expected": self.dim, "received": len(vector), "model": self.model},
                )

    async def aclose(self) -> None:
        await self._client.aclose()
