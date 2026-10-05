"""Unit tests for AST symbol extraction and chunking."""

from __future__ import annotations

import pytest

from app.models.enums import SymbolKind
from app.retrieval.hybrid import cosine_similarity
from app.retrieval.parsers.generic import chunk_generic_file
from app.retrieval.parsers.python import parse_python_symbols


@pytest.mark.unit
def test_parse_python_symbols() -> None:
    code = (
        "class Calculator:\n"
        '    """Math utils."""\n'
        "    def add(self, a: int, b: int) -> int:\n"
        "        return a + b\n\n"
        "async def async_fetch():\n"
        "    return 1\n"
    )
    symbols, chunks = parse_python_symbols(code)

    names = [s.name for s in symbols]
    assert "Calculator" in names
    assert "Calculator.add" in names
    assert "async_fetch" in names

    kinds = {s.name: s.kind for s in symbols}
    assert kinds["Calculator"] == SymbolKind.CLASS
    assert kinds["Calculator.add"] == SymbolKind.METHOD
    assert kinds["async_fetch"] == SymbolKind.ASYNC_FUNCTION

    assert len(chunks) >= 2


@pytest.mark.unit
def test_chunk_generic_file() -> None:
    text = "\n".join(f"Line {i}" for i in range(1, 101))
    chunks = chunk_generic_file(text, window_lines=30, overlap_lines=5)
    assert len(chunks) >= 3
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 30


@pytest.mark.unit
def test_cosine_similarity() -> None:
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2)) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3)) == 0.0


@pytest.mark.unit
def test_binary_suffixes_ignored() -> None:
    from app.core.ignore import ALWAYS_IGNORED_SUFFIXES, IgnoreMatcher

    assert ".pkl" in ALWAYS_IGNORED_SUFFIXES
    assert ".pickle" in ALWAYS_IGNORED_SUFFIXES
    assert ".onnx" in ALWAYS_IGNORED_SUFFIXES

    matcher = IgnoreMatcher()
    assert matcher.is_ignored("models/classifier.pkl") is True
    assert matcher.is_ignored("src/script.py") is False
