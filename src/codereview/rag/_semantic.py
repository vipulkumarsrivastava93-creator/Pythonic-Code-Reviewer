"""Semantic retrieval: embedding-based similarity search over chunks.

Pure functions over the index's chunk/vector lists. The `CodebaseIndex`
owns the data; this module owns the math (cosine search, vector means).
"""

from __future__ import annotations

from codereview.rag.chunking import Chunk
from codereview.rag.embeddings import cosine_similarity


def mean_vector(vectors: list[list[float]]) -> list[float]:
    """Element-wise mean of a list of vectors (the centroid)."""
    if not vectors:
        return []
    n = len(vectors)
    dim = len(vectors[0])
    return [sum(v[i] for v in vectors) / n for i in range(dim)]


def chunk_vector(path: str, chunks: list[Chunk],
                 vectors: list[list[float]]) -> list[float]:
    """Mean vector of the chunks belonging to `path` (the query)."""
    idx = chunk_indexes(path, chunks)
    if not idx or not vectors:
        return []
    return mean_vector([vectors[i] for i in idx])


def chunk_indexes(path: str, chunks: list[Chunk]) -> list[int]:
    """Indexes of chunks belonging to `path`."""
    return [i for i, c in enumerate(chunks) if c.file == path]


def top_k_similar(query: list[float], vectors: list[list[float]],
                  chunks: list[Chunk], exclude: set[int],
                  seen: set[str], top_k: int) -> list[Chunk]:
    """Top-K chunks by cosine similarity to `query`.

    - `exclude`: chunk indexes to skip (e.g. the file being reviewed).
    - `seen`: symbol names already retrieved structurally (dedupe).
    """
    scored = sorted(
        ((cosine_similarity(query, v), i)
         for i, v in enumerate(vectors) if i not in exclude),
        reverse=True,
    )
    hits: list[Chunk] = []
    for _, i in scored:
        chunk = chunks[i]
        if chunk.symbol in seen:
            continue
        seen.add(chunk.symbol)
        hits.append(chunk)
        if len(hits) >= top_k:
            break
    return hits