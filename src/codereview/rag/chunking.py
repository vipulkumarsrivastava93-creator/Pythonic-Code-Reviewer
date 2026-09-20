"""AST-based chunking: split source into self-contained symbol chunks.

**Why chunk by AST, not by line count?**

Prose chunking (every N lines) is wrong for code: a function split across
two chunks loses its meaning, and a chunk that starts mid-function is
garbage to an embedding model. The natural unit of code is a *symbol* — a
class or function — which is exactly what the AST gives us.

Each chunk is a compact, self-contained description of one symbol:

    Chunk(
        file="base.py",
        symbol="VisitorDetector",
        kind="class",
        signature="class VisitorDetector(Detector)",
        docstring="Base class for AST-walking detectors...",
        body="attrs: rule; methods: visit(), _make_visitor()",
    )

The `body` is a *summary*, not the full source — the full body would blow
up the prompt and the embedding. We keep just enough for the model to know
what the symbol does and how it is shaped.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from codereview.rag._ast_utils import (
    assign_targets,
    first_docstring_line,
    format_args,
    name_of,
)


@dataclass(frozen=True)
class Chunk:
    """A self-contained description of one code symbol (class or function)."""

    file: str            # relative path, e.g. "analyzers/base.py"
    symbol: str          # e.g. "VisitorDetector"
    kind: str            # "class" | "function" | "method"
    signature: str       # e.g. "class VisitorDetector(Detector)"
    docstring: str = ""  # first line of the docstring, if any
    body: str = ""       # compact summary of the symbol's contents

    def to_text(self) -> str:
        """Render the chunk as text for embedding / prompt injection."""
        parts = [f"{self.kind} {self.signature}"]
        if self.docstring:
            parts.append(f"docstring: {self.docstring}")
        if self.body:
            parts.append(f"body: {self.body}")
        return "\n".join(parts)


def render_related(chunks: list[Chunk]) -> str:
    """Render retrieved chunks as compact prompt text.

    One line per chunk: file, kind, symbol, signature, and first docstring
    line. Empty string when there is nothing to show.
    """
    if not chunks:
        return ""
    lines = []
    for c in chunks:
        lines.append(f"  {c.file}: {c.kind} {c.symbol} — {c.signature}")
        if c.docstring:
            lines.append(f"      {c.docstring}")
    return "\n".join(lines)


class Chunker:
    """Splits Python source into self-contained symbol chunks.

    Owns all AST-walking logic: given a source string or file path, it
    produces one `Chunk` per top-level class or function. The chunking
    strategy (what counts as a symbol, how bodies are summarized) lives
    here so the rest of the RAG pipeline just consumes `Chunk`s.
    """

    def chunk_source(self, source: str, path: str = "<string>") -> list[Chunk]:
        """Chunk a single source string into symbol chunks.

        Returns an empty list if the source cannot be parsed (the caller can
        decide whether that is an error or just "nothing to index").
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        chunks: list[Chunk] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                chunks.append(self._chunk_function(node, path))
            elif isinstance(node, ast.ClassDef):
                chunks.append(self._chunk_class(node, path))
        return chunks

    def chunk_file(self, path: str | Path) -> list[Chunk]:
        """Chunk a file on disk. Returns [] if unreadable or unparseable."""
        p = Path(path)
        try:
            source = p.read_text(encoding="utf-8")
        except OSError:
            return []
        return self.chunk_source(source, str(p))

    # ---- private: AST -> Chunk builders ----

    def _chunk_class(self, node: ast.ClassDef, path: str) -> Chunk:
        """Build a Chunk for a class: signature, docstring, member summary."""
        bases = ", ".join(name_of(b) for b in node.bases if name_of(b))
        signature = f"class {node.name}({bases})" if bases else f"class {node.name}"
        return Chunk(
            file=path,
            symbol=node.name,
            kind="class",
            signature=signature,
            docstring=first_docstring_line(node),
            body=self._summarize_body(node),
        )

    def _chunk_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                        path: str) -> Chunk:
        """Build a Chunk for a top-level function."""
        return Chunk(
            file=path,
            symbol=node.name,
            kind="function",
            signature=f"def {node.name}({format_args(node.args)})",
            docstring=first_docstring_line(node),
            body="",
        )

    def _summarize_body(self, node: ast.ClassDef) -> str:
        """Compact summary of a class body: attributes and method signatures.

        Each method carries its first docstring line so the embedding
        captures *behavior*, not just names — two classes with same-named
        methods but different logic now separate correctly.
        """
        attrs: list[str] = []
        methods: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                for target in assign_targets(stmt):
                    if target:
                        attrs.append(target)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(self._method_summary(stmt))
        parts = []
        if attrs:
            parts.append(f"attrs: {', '.join(attrs)}")
        if methods:
            parts.append(f"methods: {', '.join(methods)}")
        return "; ".join(parts)

    @staticmethod
    def _method_summary(stmt: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """One method as 'name(args) — first docstring line'."""
        summary = f"{stmt.name}({format_args(stmt.args)})"
        doc = first_docstring_line(stmt)
        if doc:
            summary += f" — {doc}"
        return summary