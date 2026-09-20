"""Retrieval-Augmented Generation for the LLM reviewer.

This package gives the LLM *cross-file context*: when reviewing one file, it
can see the base classes it inherits from, the modules it imports, and the
sibling detectors that follow the same pattern. Without this, the model
reviews each file in isolation and hallucinates relationships that don't
exist.

Two retrieval paths are combined (hybrid retrieval):

1. **Structural (AST graph)** — exact and deterministic. The AST already
   tells us inheritance, imports, and callers; we don't need math to find
   them. This is the primary index.
2. **Semantic (embeddings + cosine)** — fuzzy. Finds "code that does the
   same job with the same shape" even when there is no import link between
   the files. This is the secondary index.

Pipeline (per review run):

    index = CodebaseIndex.build(root)      # chunk + embed once
    related = index.related_for(path)      # per-file retrieval
    prompt = build_user_prompt(..., related=related)

Everything is stdlib-only except the embedding call, which talks to the
local Ollama runtime over HTTP (same privacy boundary as the reviewer).
"""

from __future__ import annotations

from codereview.rag.chunking import Chunk, Chunker, render_related
from codereview.rag.embeddings import EmbeddingClient, cosine_similarity
from codereview.rag.index import CodebaseIndex

__all__ = [
    "Chunk",
    "Chunker",
    "CodebaseIndex",
    "EmbeddingClient",
    "cosine_similarity",
    "render_related",
]