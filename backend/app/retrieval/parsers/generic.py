"""Generic line-window chunker for non-Python or unparsed files."""

from __future__ import annotations

from app.models.enums import ChunkType
from app.retrieval.parsers.python import ParsedChunk


def chunk_generic_file(
    content: str,
    *,
    window_lines: int = 60,
    overlap_lines: int = 10,
    chunk_type: ChunkType = ChunkType.WINDOW,
) -> list[ParsedChunk]:
    """Slice raw text into overlapping line windows."""
    lines = content.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return []

    chunks: list[ParsedChunk] = []
    chunk_idx = 0
    step = max(1, window_lines - overlap_lines)

    for start in range(0, total_lines, step):
        end = min(total_lines, start + window_lines)
        chunk_lines = lines[start:end]
        text = "\n".join(chunk_lines)
        if not text.strip():
            continue

        chunks.append(
            ParsedChunk(
                chunk_index=chunk_idx,
                chunk_type=chunk_type,
                start_line=start + 1,
                end_line=end,
                symbol_name=None,
                content=text,
            )
        )
        chunk_idx += 1
        if end >= total_lines:
            break

    return chunks
