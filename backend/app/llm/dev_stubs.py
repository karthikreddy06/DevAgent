"""DEV-ONLY providers. Explicitly not AI, and forbidden in production.

Both classes are gated behind ``ALLOW_DEV_PROVIDERS=true`` and are refused when
``ENV=production`` (see ``Settings._validate_security_posture``). They exist so
the pipeline - real clone, real indexing, real sandbox, real tests - can be
exercised offline, and so tests have a deterministic LLM double without mocking
any tool or agent logic.

* :class:`ReplayChatProvider` - replays a scripted list of responses. It never
  pretends to reason; when the script runs out it raises.
* :class:`HashingEmbeddingProvider` - deterministic token-hash vectors. It is
  *not* semantic search; it supports exact-token similarity only.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Final

from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.llm.base import (
    EmbeddingProvider,
    EmbeddingResult,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMUsage,
    ResponseFormat,
)

logger = get_logger(__name__)

_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}")
_CHARS_PER_TOKEN: Final[int] = 4


class ReplayChatProvider(LLMProvider):
    """Replays scripted responses from a JSON file. NOT an AI model."""

    name = "replay"
    dev_only = True

    def __init__(
        self,
        *,
        script_path: str | Path,
        model: str = "replay-scripted",
        max_tokens: int = 4096,
        timeout_seconds: float = 1.0,
        max_retries: int = 0,
        repeat_last: bool = False,
    ) -> None:
        super().__init__(
            model=model,
            temperature=0.0,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        self._script_path = Path(script_path)
        self._responses = self._load(self._script_path)
        self._repeat_last = repeat_last
        self._index = 0

    @staticmethod
    def _load(path: Path) -> list[str]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProviderError("Replay script not found", details={"path": str(path)}) from exc
        except ValueError as exc:
            raise ProviderError("Replay script is not valid JSON", details={"path": str(path)}) from exc
        if isinstance(raw, dict) and "responses" in raw:
            raw = raw["responses"]
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ProviderError("Replay script must be a JSON list of strings", details={"path": str(path)})
        if not raw:
            raise ProviderError("Replay script is empty", details={"path": str(path)})
        return [str(item) for item in raw]

    @property
    def calls_made(self) -> int:
        return self._index

    async def complete(
        self,
        messages: Sequence[LLMMessage],
        *,
        response_format: ResponseFormat = "text",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        if self._index >= len(self._responses):
            if not self._repeat_last:
                raise ProviderError(
                    "Replay script exhausted: more LLM calls were made than the script provides",
                    details={"calls": self._index, "script": str(self._script_path)},
                )
            text = self._responses[-1]
        else:
            text = self._responses[self._index]
            self._index += 1

        logger.warning("dev_only_replay_provider_used", script=str(self._script_path), call=self._index)
        prompt_chars = sum(len(message.content) for message in messages)
        return LLMResponse(
            text=text,
            model=self.model,
            provider=self.name,
            usage=LLMUsage(
                prompt_tokens=prompt_chars // _CHARS_PER_TOKEN,
                completion_tokens=len(text) // _CHARS_PER_TOKEN,
            ),
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        response = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
        for start in range(0, len(response.text), 240):
            yield response.text[start : start + 240]


class HashingEmbeddingProvider(EmbeddingProvider):
    """Deterministic token-hash embeddings. NOT semantic search."""

    name = "hashing"
    dev_only = True

    def __init__(self, *, model: str = "hashing-dev", dim: int, batch_size: int = 256) -> None:
        super().__init__(model=model, dim=dim, batch_size=batch_size, timeout_seconds=1.0)

    def _vectorise(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(text.lower())
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0 if digest[4] % 2 == 0 else -1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        vectors: list[list[float]] = [self._vectorise(text) for text in texts]
        logger.warning("dev_only_hashing_embedder_used", texts=len(texts), dim=self.dim)
        return EmbeddingResult(vectors=vectors, model=self.model, provider=self.name, dim=self.dim)
