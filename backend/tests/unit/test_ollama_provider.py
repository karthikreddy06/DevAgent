"""Unit tests for Ollama providers (chat + embeddings)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
import pytest

from app.core.errors import ProviderError
from app.llm.ollama import OllamaEmbeddingProvider


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedding_empty_input() -> None:
    provider = OllamaEmbeddingProvider(model="nomic-embed-text:latest", dim=768)
    try:
        res = await provider.embed([])
        assert res.vectors == []
        assert res.count == 0
        assert res.model == "nomic-embed-text:latest"
        assert res.dim == 768
    finally:
        await provider.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedding_single_text() -> None:
    dummy_vec = [0.1] * 768
    provider = OllamaEmbeddingProvider(model="nomic-embed-text:latest", dim=768)

    with patch("app.llm.ollama.post_json", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {"embeddings": [dummy_vec]}

        try:
            res = await provider.embed(["Single text to embed"])
            assert res.count == 1
            assert len(res.vectors) == 1
            assert len(res.vectors[0]) == 768
            assert res.vectors[0] == dummy_vec

            # Verify it sends single string input in payload
            assert mock_post.call_count == 1
            call_kwargs = mock_post.call_args.kwargs
            assert call_kwargs["payload"] == {
                "model": "nomic-embed-text:latest",
                "input": "Single text to embed",
            }
        finally:
            await provider.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedding_multiple_texts() -> None:
    dummy_vec_1 = [0.1] * 768
    dummy_vec_2 = [0.2] * 768
    dummy_vec_3 = [0.3] * 768
    provider = OllamaEmbeddingProvider(model="nomic-embed-text:latest", dim=768)

    with patch("app.llm.ollama.post_json", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = [
            {"embeddings": [dummy_vec_1]},
            {"embeddings": [dummy_vec_2]},
            {"embeddings": [dummy_vec_3]},
        ]

        try:
            texts = ["First line", "Second line", "Third line"]
            res = await provider.embed(texts)
            assert res.count == 3
            assert len(res.vectors) == 3
            for vec in res.vectors:
                assert len(vec) == 768
            assert res.vectors[0] == dummy_vec_1
            assert res.vectors[1] == dummy_vec_2
            assert res.vectors[2] == dummy_vec_3

            assert mock_post.call_count == 3
        finally:
            await provider.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedding_dimension_mismatch() -> None:
    dummy_vec_short = [0.1] * 384  # Expects 768
    provider = OllamaEmbeddingProvider(model="nomic-embed-text:latest", dim=768)

    with patch("app.llm.ollama.post_json", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {"embeddings": [dummy_vec_short]}

        try:
            with pytest.raises(ProviderError, match="Embedding dimension mismatch"):
                await provider.embed(["Test text"])
        finally:
            await provider.aclose()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ollama_embedding_alternative_format() -> None:
    # Some Ollama versions return flat "embedding" key
    dummy_vec = [0.5] * 768
    provider = OllamaEmbeddingProvider(model="nomic-embed-text:latest", dim=768)

    with patch("app.llm.ollama.post_json", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = {"embedding": dummy_vec}

        try:
            res = await provider.embed(["Alternative response shape test"])
            assert res.count == 1
            assert len(res.vectors[0]) == 768
        finally:
            await provider.aclose()
