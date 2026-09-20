"""Embeddings: turn text chunks into vectors via a local embedding model.

**What is an embedding?**

An embedding model converts text into a list of numbers (a vector) where
*semantically similar* text produces *numerically similar* vectors. The
numbers themselves are opaque — what matters is that "class that holds
data" and "dataclass candidate" end up close together in vector space even
though they share no words.

**Why local?**

We reuse the same privacy boundary as the reviewer: the embedding call goes
to the local Ollama runtime over `localhost`, so code never leaves the
machine. The default model is `nomic-embed-text` (~274 MB), Ollama's
standard embedding model.

**How the call works**

Ollama exposes an OpenAI-compatible `/v1/embeddings` endpoint:

    POST http://localhost:11434/v1/embeddings
    {"model": "nomic-embed-text", "input": "class VisitorDetector..."}

    -> {"data": [{"embedding": [0.12, -0.04, ...]}]}

The response is a list of floats (768 for nomic-embed-text). We store one
vector per chunk and compare them with cosine similarity.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

DEFAULT_EMBED_MODEL = "nomic-embed-text"
# Ollama's native embeddings endpoint (the OpenAI-compatible /v1/embeddings
# route is not available in all Ollama versions).
DEFAULT_EMBED_URL = "http://localhost:11434/api/embed"

# A vector is a list of floats. Type alias for readability.
Vector = list[float]


class EmbeddingError(Exception):
    """Raised when the embedding endpoint is unreachable or returns garbage."""


@dataclass
class EmbeddingClient:
    """A thin client for an OpenAI-compatible embeddings endpoint.

    Resolution order for the endpoint:
      1. `CODEREVIEW_EMBED_URL` env var (explicit override).
      2. Local Ollama on `localhost:11434` (default).
    """

    url: str = ""
    model: str = ""
    timeout: float = 30.0

    def __post_init__(self) -> None:
        self.url = self.url or os.environ.get("CODEREVIEW_EMBED_URL", DEFAULT_EMBED_URL)
        self.model = self.model or os.environ.get(
            "CODEREVIEW_EMBED_MODEL", DEFAULT_EMBED_MODEL
        )

    def embed(self, text: str) -> Vector:
        """Embed a single text string into a vector."""
        body = json.dumps({"model": self.model, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            self.url, data=body, headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EmbeddingError(
                f"Embedding endpoint returned HTTP {exc.code}: "
                f"{exc.read().decode('utf-8', errors='replace')[:200]}"
            ) from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise EmbeddingError(
                f"Embedding endpoint unreachable at {self.url}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise EmbeddingError("Embedding endpoint returned non-JSON") from exc

        # Ollama /api/embed returns {"embeddings": [[...]]}; the OpenAI
        # /v1/embeddings shape is {"data": [{"embedding": [...]}]}. Accept both.
        try:
            if "embeddings" in payload:
                return payload["embeddings"][0]
            return payload["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise EmbeddingError(
                "Embedding response missing 'embeddings[0]' or 'data[0].embedding'"
            ) from exc

    def embed_many(self, texts: list[str],
                   progress: Any = None) -> list[Vector]:
        """Embed a list of texts. Falls back to one-by-one on failure.

        `progress` (optional) is a callback `progress(done, total)` invoked
        after each text is embedded, so callers can show progress.
        """
        vectors: list[Vector] = []
        total = len(texts)
        for i, text in enumerate(texts, start=1):
            vectors.append(self.embed(text))
            if progress is not None:
                progress(i, total)
        return vectors


def cosine_similarity(a: Vector, b: Vector) -> float:
    """Cosine similarity between two vectors: 1.0 (same) .. -1.0 (opposite).

    The cosine of the angle between two vectors. It measures *direction*
    similarity, ignoring magnitude — which is what we want: a long chunk and
    a short chunk about the same topic should score the same.

        cos(a, b) = (a . b) / (|a| * |b|)

    Pure Python, no dependencies. Fine for thousands of chunks.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector length mismatch: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)