"""AST-based Python code parser for symbol extraction and semantic chunking."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from app.models.enums import ChunkType, SymbolKind


@dataclass(frozen=True, slots=True)
class ParsedSymbol:
    name: str
    kind: SymbolKind
    start_line: int
    end_line: int
    signature: str | None
    docstring: str | None


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    chunk_index: int
    chunk_type: ChunkType
    start_line: int
    end_line: int
    symbol_name: str | None
    content: str


def parse_python_symbols(source: str) -> tuple[list[ParsedSymbol], list[ParsedChunk]]:
    """Parse python source code into symbols and symbol/block chunks."""
    symbols: list[ParsedSymbol] = []
    chunks: list[ParsedChunk] = []

    lines = source.splitlines()
    total_lines = len(lines)
    if total_lines == 0:
        return symbols, chunks

    try:
        tree = ast.parse(source)
    except SyntaxError:
        # Fall back to whole-file or window chunking if there are syntax errors
        content = "\n".join(lines[:100])
        chunks.append(
            ParsedChunk(
                chunk_index=0,
                chunk_type=ChunkType.WINDOW,
                start_line=1,
                end_line=min(total_lines, 100),
                symbol_name=None,
                content=content,
            )
        )
        return symbols, chunks

    chunk_idx = 0
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = SymbolKind.ASYNC_FUNCTION if isinstance(node, ast.AsyncFunctionDef) else SymbolKind.FUNCTION
            start = node.lineno
            end = node.end_lineno or start
            docstring = ast.get_docstring(node)
            # Build simple signature representation
            args = [arg.arg for arg in node.args.args]
            sig = f"def {node.name}({', '.join(args)})"

            symbols.append(
                ParsedSymbol(
                    name=node.name,
                    kind=kind,
                    start_line=start,
                    end_line=end,
                    signature=sig,
                    docstring=docstring,
                )
            )
            chunks.append(
                ParsedChunk(
                    chunk_index=chunk_idx,
                    chunk_type=ChunkType.SYMBOL,
                    start_line=start,
                    end_line=end,
                    symbol_name=node.name,
                    content="\n".join(lines[start - 1 : end]),
                )
            )
            chunk_idx += 1

        elif isinstance(node, ast.ClassDef):
            start = node.lineno
            end = node.end_lineno or start
            docstring = ast.get_docstring(node)
            bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
            sig = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"

            symbols.append(
                ParsedSymbol(
                    name=node.name,
                    kind=SymbolKind.CLASS,
                    start_line=start,
                    end_line=end,
                    signature=sig,
                    docstring=docstring,
                )
            )
            chunks.append(
                ParsedChunk(
                    chunk_index=chunk_idx,
                    chunk_type=ChunkType.SYMBOL,
                    start_line=start,
                    end_line=end,
                    symbol_name=node.name,
                    content="\n".join(lines[start - 1 : end]),
                )
            )
            chunk_idx += 1

            # Sub-methods
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    m_start = item.lineno
                    m_end = item.end_lineno or m_start
                    m_doc = ast.get_docstring(item)
                    m_args = [arg.arg for arg in item.args.args]
                    m_sig = f"{node.name}.{item.name}({', '.join(m_args)})"
                    full_name = f"{node.name}.{item.name}"
                    symbols.append(
                        ParsedSymbol(
                            name=full_name,
                            kind=SymbolKind.METHOD,
                            start_line=m_start,
                            end_line=m_end,
                            signature=m_sig,
                            docstring=m_doc,
                        )
                    )

    if not chunks:
        # No top-level functions or classes; chunk with window
        chunks.append(
            ParsedChunk(
                chunk_index=0,
                chunk_type=ChunkType.BLOCK,
                start_line=1,
                end_line=min(total_lines, 80),
                symbol_name=None,
                content="\n".join(lines[:80]),
            )
        )

    return symbols, chunks
