"""Chunking dispatcher based on file extension and language conventions."""

from __future__ import annotations

from pathlib import PurePosixPath

from app.models.enums import ChunkType
from app.retrieval.parsers.generic import chunk_generic_file
from app.retrieval.parsers.python import ParsedChunk, ParsedSymbol, parse_python_symbols


def chunk_file_content(path: str, content: str) -> tuple[list[ParsedSymbol], list[ParsedChunk]]:
    """Generate symbols and chunks for a given file path and text content."""
    posix_path = PurePosixPath(path)
    suffix = posix_path.suffix.lower()

    if suffix == ".py":
        return parse_python_symbols(content)

    if suffix in (".md", ".rst", ".txt"):
        return [], chunk_generic_file(content, window_lines=50, overlap_lines=10, chunk_type=ChunkType.DOC)

    if suffix in (".json", ".yaml", ".yml", ".toml", ".ini"):
        return [], chunk_generic_file(content, window_lines=60, overlap_lines=5, chunk_type=ChunkType.CONFIG)

    # General source code (.js, .ts, .tsx, .jsx, .go, .rs, .c, .cpp, etc.)
    return [], chunk_generic_file(content, window_lines=60, overlap_lines=15, chunk_type=ChunkType.WINDOW)
