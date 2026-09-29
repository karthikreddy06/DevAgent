"""Provider factory: the only module that knows about concrete providers.

Adding a vendor means adding a module and one branch here; no agent, service or
route changes.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings, get_settings
from app.core.errors import ProviderError
from app.llm.anthropic import AnthropicChatProvider
from app.llm.base import EmbeddingProvider, LLMProvider
from app.llm.dev_stubs import HashingEmbeddingProvider, ReplayChatProvider
from app.llm.ollama import OllamaChatProvider, OllamaEmbeddingProvider
from app.llm.openai import OpenAIChatProvider, OpenAIEmbeddingProvider


def build_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Construct the configured chat provider."""
    resolved = settings or get_settings()
    common: dict[str, Any] = {
        "model": resolved.llm_model,
        "temperature": resolved.llm_temperature,
        "max_tokens": resolved.llm_max_output_tokens,
        "timeout_seconds": resolved.llm_timeout_seconds,
        "max_retries": resolved.llm_max_retries,
    }

    if resolved.llm_provider == "openai":
        return OpenAIChatProvider(
            api_key=resolved.llm_api_key_value or "",
            base_url=resolved.llm_base_url,
            **common,
        )
    if resolved.llm_provider == "anthropic":
        return AnthropicChatProvider(
            api_key=resolved.llm_api_key_value or "",
            base_url=resolved.llm_base_url,
            **common,
        )
    if resolved.llm_provider == "ollama":
        return OllamaChatProvider(base_url=resolved.llm_base_url, **common)
    if resolved.llm_provider == "replay":
        if not resolved.dev_llm_script:
            raise ProviderError("LLM_PROVIDER=replay requires DEV_LLM_SCRIPT to point at a scripted JSON response file")
        return ReplayChatProvider(
            script_path=resolved.dev_llm_script, model=resolved.llm_model, max_tokens=resolved.llm_max_output_tokens
        )
    raise ProviderError("Unsupported LLM provider", details={"provider": resolved.llm_provider})


def build_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Construct the configured embedding provider."""
    resolved = settings or get_settings()

    if resolved.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            api_key=resolved.llm_api_key_value or "",
            model=resolved.embedding_model,
            dim=resolved.embedding_dim,
            base_url=resolved.llm_base_url,
            batch_size=resolved.embedding_batch_size,
            timeout_seconds=resolved.llm_timeout_seconds,
        )
    if resolved.embedding_provider == "ollama":
        return OllamaEmbeddingProvider(
            model=resolved.embedding_model,
            dim=resolved.embedding_dim,
            base_url=resolved.llm_base_url,
            batch_size=min(resolved.embedding_batch_size, 32),
        )
    if resolved.embedding_provider == "hashing":
        return HashingEmbeddingProvider(model=resolved.embedding_model, dim=resolved.embedding_dim)
    raise ProviderError("Unsupported embedding provider", details={"provider": resolved.embedding_provider})


def provider_status(settings: Settings | None = None) -> dict[str, Any]:
    """Non-secret provider status for GET /api/config and the UI banner."""
    resolved = settings or get_settings()
    status: dict[str, Any] = {
        "llm_provider": resolved.llm_provider,
        "llm_model": resolved.llm_model,
        "embedding_provider": resolved.embedding_provider,
        "embedding_model": resolved.embedding_model,
        "embedding_dim": resolved.embedding_dim,
        "dev_providers_allowed": resolved.allow_dev_providers,
        "llm_ready": True,
        "embedding_ready": True,
        "llm_error": None,
        "embedding_error": None,
    }
    try:
        build_llm_provider(resolved)
    except ProviderError as exc:
        status["llm_ready"] = False
        status["llm_error"] = exc.message
    try:
        build_embedding_provider(resolved)
    except ProviderError as exc:
        status["embedding_ready"] = False
        status["embedding_error"] = exc.message
    return status
