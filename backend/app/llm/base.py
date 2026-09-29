"""Provider-independent LLM and embedding abstraction.

Nothing above ``app/llm`` knows which vendor is in use: agents speak
:class:`LLMMessage` / :class:`LLMResponse`, and the factory picks a provider from
configuration. Credentials are read from the environment and validated when a
provider is constructed (see ``app/llm/factory.py``), so a misconfigured
deployment reports a clear error instead of failing at import time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["system", "user", "assistant"]
ResponseFormat = Literal["text", "json"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A single chat message."""

    role: Role
    content: str

    @classmethod
    def system(cls, content: str) -> LLMMessage:
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> LLMMessage:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> LLMMessage:
        return cls(role="assistant", content=content)

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True, slots=True)
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: LLMUsage) -> LLMUsage:
        return LLMUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: LLMUsage = LLMUsage()
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider: str
    dim: int

    @property
    def count(self) -> int:
        return len(self.vectors)


class LLMProvider(ABC):
    """Chat-completion provider."""

    name: str = "base"
    model: str = "unknown"
    dev_only: bool = False

    def __init__(
        self,
        *,
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    @property
    def is_dev_only(self) -> bool:
        """True for clearly labelled non-AI stubs (dev/test only)."""
        return self.dev_only

    def describe(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "model": self.model,
            "dev_only": self.is_dev_only,
            "max_tokens": self.max_tokens,
        }

    @abstractmethod
    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_format: ResponseFormat = "text",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Return a completion. Must raise ProviderError on failure."""

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """Yield text chunks. Default implementation is not incremental."""
        response = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        yield response.text

    async def aclose(self) -> None:
        """Release network resources."""
        return None


class EmbeddingProvider(ABC):
    """Embedding provider used by the RAG pipeline."""

    name: str = "base"
    dev_only: bool = False

    def __init__(self, *, model: str, dim: int, batch_size: int = 64, timeout_seconds: float = 120.0) -> None:
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self.timeout_seconds = timeout_seconds

    @property
    def is_dev_only(self) -> bool:
        return self.dev_only

    def describe(self) -> dict[str, Any]:
        return {"provider": self.name, "model": self.model, "dim": self.dim, "dev_only": self.is_dev_only}

    @abstractmethod
    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        """Embed a batch of texts (implementations may split into batches)."""

    async def aclose(self) -> None:
        return None
