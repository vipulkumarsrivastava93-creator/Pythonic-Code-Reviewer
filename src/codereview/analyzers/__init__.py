"""Analysis entry point: run all registered detectors and aggregate issues."""

from __future__ import annotations

import ast

from codereview.analyzers.detectors import REGISTRY
from codereview.report import Issue


def analyze(tree: ast.AST) -> list[Issue]:
    """Run every registered detector over `tree` and return combined issues."""
    issues: list[Issue] = []
    for detector in REGISTRY:
        issues.extend(detector.detect(tree))
    return issues


__all__ = ["analyze"]