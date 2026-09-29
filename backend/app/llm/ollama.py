"""Ollama provider: fully local inference (chat + embeddings).

Useful for air-gapped installations where repository code must never leave the
host. Set ``LLM_PROVIDER=ollama`` and ``LLM_BASE_URL=http://localhost:11434``.
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
from app.llm.http_client import post_json

DEFAULT_BASE_URL = "http://localhost:11434"
_JSON_HEADERS: dict[str, str] = {"Content-Type": "application/json"}


class OllamaChatProvider(LLMProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: float = 300.0,
        max_retries: int = 1,
    ) -> None:
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
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
            "stream": stream,
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_predict": self.max_tokens if max_tokens is None else max_tokens,
            },
        }
        if response_format == "json":
            payload["format"] = "json"
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
            f"{self._base_url}/api/chat",
            payload=self._payload(
                messages,
                response_format=response_format,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
            ),
            headers=_JSON_HEADERS,
            timeout_seconds=self.timeout_seconds,
            max_retries=self.max_retries,
            provider=self.name,
        )
        message = (data.get("message") or {}) if isinstance(data, dict) else {}
        finish = data.get("done_reason")
        return LLMResponse(
            text=str(message.get("content", "")),
            model=str(data.get("model", self.model)),
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
                completion_tokens=int(data.get("eval_count", 0) or 0),
            ),
            finish_reason=str(finish) if finish else None,
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
                "POST", f"{self._base_url}/api/chat", json=payload, timeout=self.timeout_seconds
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    raise ProviderError(
                        "ollama streaming request failed",
                        details={"status": response.status_code},
                        retryable=True,
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except ValueError:
                        continue
                    content = (parsed.get("message") or {}).get("content")
                    if content:
                        yield str(content)
        except httpx.HTTPError as exc:
            raise ProviderError("ollama streaming failed", details={"reason": type(exc).__name__}) from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class OllamaEmbeddingProvider(EmbeddingProvider):
    name = "ollama"

    def __init__(
        self,
        *,
        model: str,
        dim: int,
        base_url: str | None = None,
        batch_size: int = 32,
        timeout_seconds: float = 300.0,
    ) -> None:
        super().__init__(model=model, dim=dim, batch_size=batch_size, timeout_seconds=timeout_seconds)
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(vectors=[], model=self.model, provider=self.name, dim=self.dim)
        vectors: list[list[float]] = []
        for text in texts:
            data = await post_json(
                self._client,
                f"{self._base_url}/api/embed",
                payload={"model": self.model, "input": text},
                headers=_JSON_HEADERS,
                timeout_seconds=self.timeout_seconds,
                max_retries=1,
                provider=self.name,
            )
            embeddings = data.get("embeddings")
            if isinstance(embeddings, list) and len(embeddings) > 0 and isinstance(embeddings[0], list):
                raw_vector = embeddings[0]
            elif isinstance(data.get("embedding"), list):
                raw_vector = data["embedding"]
            else:
                raise ProviderError("ollama returned an unexpected embedding response")

            vector = [float(value) for value in raw_vector]
            if len(vector) != self.dim:
                raise ProviderError(
                    "Embedding dimension mismatch",
                    details={"expected": self.dim, "received": len(vector), "model": self.model},
                )
            vectors.append(vector)
        return EmbeddingResult(vectors=vectors, model=self.model, provider=self.name, dim=self.dim)

    async def aclose(self) -> None:
        await self._client.aclose()
