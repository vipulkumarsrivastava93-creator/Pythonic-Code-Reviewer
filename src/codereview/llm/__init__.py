"""Local/remote LLM reviewer adapter (optional, flag-gated)."""

from __future__ import annotations

from codereview.llm.installer import (
    DEFAULT_MODEL,
    ModelInstallError,
    ensure_model,
    install_ollama,
    installed_models,
    model_pulled,
    ollama_installed,
    pick_best_model,
)
from codereview.llm.reviewer import (
    LLMError,
    LLMReviewer,
    check_runtime,
    review_with_llm,
)

__all__ = [
    "DEFAULT_MODEL",
    "LLMError",
    "LLMReviewer",
    "ModelInstallError",
    "check_runtime",
    "ensure_model",
    "install_ollama",
    "installed_models",
    "model_pulled",
    "ollama_installed",
    "pick_best_model",
    "review_with_llm",
]