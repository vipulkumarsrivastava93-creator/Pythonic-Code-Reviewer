"""Hybrid codebase index: structural AST graph + semantic embeddings.

**Why hybrid?**

Pure cosine similarity cannot reliably match inherited classes — the
embedding of "PreferDataclass" is about dataclasses, not about its base
class "VisitorDetector". The inheritance link is *structural*, not
semantic. So we combine two retrieval paths:

1. **Structural** — walk the AST once and build a symbol graph:
   - `symbols[path][name] -> Chunk` (look up by exact name)
   - `imports[path] -> set[module]` (what each file imports)
   - `bases[name] -> set[base_name]` (inheritance)
   These are exact, deterministic, and free.

2. **Semantic** — embed each chunk and search by cosine similarity. This
   finds *sibling* code: classes that follow the same pattern but have no
   import link between them (e.g. two detectors both subclassing
   VisitorDetector via base.py, without importing each other).

Retrieval for a file = structural hits (imports, bases, callers) + top-K
semantic neighbors, deduplicated, ranked, and rendered as short text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codereview.rag._graph import class_bases, import_names, module_name
from codereview.rag._semantic import chunk_vector, chunk_indexes, top_k_similar
from codereview.rag.cache import load as cache_load, restore as cache_restore, save as cache_save
from codereview.rag.chunking import Chunk, Chunker
from codereview.rag.embeddings import EmbeddingClient


@dataclass
class CodebaseIndex:  # noqa: DES001 - cohesive: owns index data + retrieval
    """The in-memory index: chunks + vectors + structural graph."""

    chunks: list[Chunk] = field(default_factory=list)
    vectors: list[list[float]] = field(default_factory=list)
    # Structural graph: symbol name -> chunk (globally unique by name).
    symbols: dict[str, Chunk] = field(default_factory=dict)
    # Structural graph: module path -> set of imported module names.
    imports: dict[str, set[str]] = field(default_factory=dict)
    # Structural graph: class name -> set of base class names.
    bases: dict[str, set[str]] = field(default_factory=dict)
    # Structural graph: dotted module name -> indexed file path.
    module_files: dict[str, str] = field(default_factory=dict)

    @classmethod
    def build(cls, root: str | Path, *, embedder: EmbeddingClient | None = None,
              embed: bool = True, progress: Any = None,
              use_cache: bool = True) -> "CodebaseIndex":
        """Build an index over every `.py` file under `root`.

        - Chunks are extracted structurally (no embedding needed).
        - If `embed` is True and an embedder is available, each chunk is
          embedded so semantic retrieval works. If embedding fails (no
          runtime), the index still works structurally — graceful degrade.
        - `progress` (optional) is a callback `progress(done, total)` invoked
          during embedding so callers can show progress.
        - `use_cache` (default True) persists the index to
          `.codereview/rag-index.json` in the project root and reloads it
          when no file has changed (keyed by mtimes). A cache hit skips
          chunking AND embedding — instant repeat runs.
        """
        root = Path(root)
        index = cls()
        chunker = Chunker()
        files = sorted(str(p.relative_to(root)) for p in root.rglob("*.py"))
        if use_cache:
            cached = cache_load(root, files)
            if cached is not None:
                chunks, vectors, imports, bases, module_files = cache_restore(cached)
                index.chunks = chunks
                index.vectors = vectors
                index.imports = imports
                index.bases = bases
                index.module_files = module_files
                for chunk in chunks:
                    index.symbols[chunk.symbol] = chunk
                return index
        for path in sorted(root.rglob("*.py")):
            index._index_file(path, root, chunker)
        if embed and embedder is not None:
            try:
                index.vectors = embedder.embed_many(
                    [c.to_text() for c in index.chunks],
                    progress=progress,
                )
            except Exception:
                # No embedding runtime -> structural-only index.
                index.vectors = []
        if use_cache:
            cache_save(root, files=files, chunks=index.chunks,
                       vectors=index.vectors, imports=index.imports,
                       bases=index.bases, module_files=index.module_files)
        return index

    def _index_file(self, path: Path, root: Path, chunker: Chunker) -> None:
        """Chunk one file and register it in the structural graph."""
        chunks = chunker.chunk_file(path)
        if not chunks:
            return
        rel = str(path.relative_to(root))
        for chunk in chunks:
            # Re-tag with the repo-relative path (chunk_file used abs).
            chunk = Chunk(
                file=rel, symbol=chunk.symbol, kind=chunk.kind,
                signature=chunk.signature, docstring=chunk.docstring,
                body=chunk.body,
            )
            self.chunks.append(chunk)
            self.symbols[chunk.symbol] = chunk
        self.imports[rel] = import_names(path)
        self.bases.update(class_bases(path))
        self.module_files[module_name(rel)] = rel

    # ---- retrieval ----

    def related_for(self, path: str, *, top_k: int = 5) -> list[Chunk]:
        """Chunks most relevant to reviewing `path`.

        Structural hits (imports, inherited bases) rank first — they are
        exact. Semantic neighbors (similar code elsewhere) fill the rest.
        """
        if not self.chunks:
            return []
        structural, seen = self._structural_hits(path)
        semantic = self._semantic_hits(path, seen, top_k)
        return structural[:top_k] + semantic[: max(0, top_k - len(structural))]

    def _structural_hits(self, path: str) -> tuple[list[Chunk], set[str]]:
        """Exact hits: inherited bases + imported modules of `path`."""
        hits: list[Chunk] = []
        seen: set[str] = set()
        own_symbols = self._symbols_in(path)
        for base in self._bases_of(path, own_symbols):
            self._add_unique(hits, seen, base)
        for target in self._imported_files(path):
            for chunk in self.chunks:
                if chunk.file == target:
                    self._add_unique(hits, seen, chunk)
        return hits, seen

    def _bases_of(self, path: str, own_symbols: set[str]) -> list[Chunk]:
        """Chunks for base classes of classes in `path` (external files only)."""
        hits: list[Chunk] = []
        for name, base_names in self.bases.items():
            if name not in own_symbols:
                continue
            for base in base_names:
                chunk = self.symbols.get(base)
                if chunk is not None and chunk.file != path:
                    hits.append(chunk)
        return hits

    def _imported_files(self, path: str) -> set[str]:
        """Indexed file paths that `path` imports (excluding itself)."""
        targets: set[str] = set()
        for mod in self.imports.get(path, set()):
            target = self._resolve_module(mod)
            if target and target != path:
                targets.add(target)
        return targets

    def _resolve_module(self, mod: str) -> str | None:
        """Resolve a dotted module name to an indexed file, or None.

        Tries the exact module, then walks up parent packages so
        `codereview.analyzers.detectors` matches the package's
        `__init__.py` even if only the package root is indexed.
        """
        parts = mod.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            target = self.module_files.get(candidate)
            if target:
                return target
        return None

    @staticmethod
    def _add_unique(target: list[Chunk], seen: set[str], chunk: Chunk) -> None:
        """Append `chunk` to `target` unless its symbol is already seen."""
        if chunk.symbol not in seen:
            seen.add(chunk.symbol)
            target.append(chunk)

    def _symbols_in(self, path: str) -> set[str]:
        """Symbol names defined in a given file."""
        return {c.symbol for c in self.chunks if c.file == path}

    def _semantic_hits(self, path: str, seen: set[str], top_k: int) -> list[Chunk]:
        """Top-K chunks by cosine similarity, excluding `path` and `seen`."""
        if not self.vectors or len(self.vectors) != len(self.chunks):
            return []
        query_vec = chunk_vector(path, self.chunks, self.vectors)
        if not query_vec:
            return []
        own = set(chunk_indexes(path, self.chunks))
        return top_k_similar(query_vec, self.vectors, self.chunks,
                             exclude=own, seen=seen, top_k=top_k)

    # ---- consistency pre-check ----

    def structural_signature(self, path: str) -> tuple[frozenset[str], frozenset[str]]:
        """The file's structural signature: (imports, base classes).

        Two files with the same signature follow the same structural
        pattern — same dependencies, same inheritance. Used to decide
        whether a consistency LLM call is worth making.
        """
        imports = frozenset(self.imports.get(path, set()))
        own = self._symbols_in(path)
        bases = frozenset(
            base
            for name, base_names in self.bases.items()
            if name in own
            for base in base_names
        )
        return imports, bases

    def sibling_files(self, path: str) -> set[str]:
        """Files whose classes share a base class with `path` (siblings).

        Siblings are the structural counterpart of the semantic neighbors:
        classes that follow the same pattern (e.g. two detectors both
        subclassing `VisitorDetector`). Excludes `path` itself.
        """
        own = self._symbols_in(path)
        own_bases = {
            base
            for name, base_names in self.bases.items()
            if name in own
            for base in base_names
        }
        siblings: set[str] = set()
        for name, base_names in self.bases.items():
            if name in own or not (base_names & own_bases):
                continue
            chunk = self.symbols.get(name)
            if chunk is not None and chunk.file != path:
                siblings.add(chunk.file)
        return siblings

    def siblings_match(self, path: str) -> bool:
        """True if the file's structural signature matches a sibling's.

        If so, the file follows the same pattern as at least one sibling —
        the consistency LLM call would almost certainly return no
        deviations, so callers can skip it. Conservative: returns False
        when there are no siblings or no sibling shares the signature
        (run the LLM).
        """
        signature = self.structural_signature(path)
        return any(
            self.structural_signature(sib) == signature
            for sib in self.sibling_files(path)
        )