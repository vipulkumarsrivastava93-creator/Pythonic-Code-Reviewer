"""Disk cache for the RAG index.

The index (chunks + vectors + structural graph) is expensive to build:
chunking is fast, but embedding every chunk takes ~3s. Rebuilding it on
every run is wasteful when nothing changed. This module persists the
index to `.codereview/rag-index.json` in the project root — the same
pattern as `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`.

**Cache validity** is keyed by file mtimes: the cache is fresh only if
every indexed file's mtime matches what was recorded at build time. If
any file changed, the cache is stale and the index is rebuilt.

The cache is best-effort: any failure (corrupt JSON, missing dir, IO
error) simply means "no cache" — the caller rebuilds the index.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from codereview.rag.chunking import Chunk

CACHE_DIR_NAME = ".codereview"
CACHE_FILE_NAME = "rag-index.json"
CACHE_VERSION = 1


def cache_path(root: str | Path) -> Path:
    """The cache file path for a project root: `<root>/.codereview/rag-index.json`."""
    return Path(root) / CACHE_DIR_NAME / CACHE_FILE_NAME


def _file_mtimes(root: Path, files: list[str]) -> dict[str, float]:
    """mtime per indexed file, used to validate cache freshness."""
    mtimes: dict[str, float] = {}
    for rel in files:
        try:
            mtimes[rel] = (root / rel).stat().st_mtime
        except OSError:
            mtimes[rel] = -1.0  # missing file -> always stale
    return mtimes


def load(root: str | Path, files: list[str]) -> dict[str, Any] | None:
    """Load a fresh cache, or None if missing/stale/corrupt.

    `files` is the list of indexed relative paths (from the current scan).
    The cache is returned only if it exists, parses, matches CACHE_VERSION,
    and every file's mtime matches what was recorded.
    """
    path = cache_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("version") != CACHE_VERSION:
        return None
    recorded = data.get("files", {})
    if set(recorded) != set(files):
        return None
    if _file_mtimes(Path(root), files) != recorded:
        return None
    return data


def save(root: str | Path, *, files: list[str], chunks: list[Chunk],
         vectors: list[list[float]], imports: dict[str, set[str]],
         bases: dict[str, set[str]], module_files: dict[str, str]) -> None:
    """Persist the index to disk. Best-effort: failures are swallowed.

    `files` is the FULL scan list (every `.py` under root), not just files
    that produced chunks — empty `__init__.py` files must still be tracked
    so the cache is invalidated when they appear/disappear.
    """
    try:
        path = cache_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": CACHE_VERSION,
            "files": _file_mtimes(Path(root), files),
            "chunks": [asdict(c) for c in chunks],
            "vectors": vectors,
            "imports": {k: sorted(v) for k, v in imports.items()},
            "bases": {k: sorted(v) for k, v in bases.items()},
            "module_files": module_files,
        }
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        pass  # cache is best-effort; never block review


def restore(data: dict[str, Any]) -> tuple[list[Chunk], list[list[float]],
                                          dict[str, set[str]], dict[str, set[str]],
                                          dict[str, str]]:
    """Rebuild the index objects from cached JSON.

    Returns (chunks, vectors, imports, bases, module_files) ready to be
    assigned onto a `CodebaseIndex`.
    """
    chunks = [Chunk(**c) for c in data["chunks"]]
    vectors = data.get("vectors", [])
    imports = {k: set(v) for k, v in data.get("imports", {}).items()}
    bases = {k: set(v) for k, v in data.get("bases", {}).items()}
    module_files = data.get("module_files", {})
    return chunks, vectors, imports, bases, module_files