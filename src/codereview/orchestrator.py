"""Review orchestration: subclasses decide which reviewers run.

`ReviewOrchestrator` defines the review flow (file/source/tree parsing + report
assembly). Concrete flavors implement `review_tree`:
  - `OfflineOrchestrator` runs the deterministic, local detector registry.
  - Future `AgentOrchestrator` (LLM-backed) can extend the same base.
"""

from __future__ import annotations

import abc
import ast
from pathlib import Path

from codereview.analyzers import analyze
from codereview.report import Report


class ReviewOrchestrator(abc.ABC):
    """Base orchestrator: a review flow produces a Report from tree/source/file."""

    @abc.abstractmethod
    def review_tree(self, tree: ast.AST, path: str = "<string>") -> Report:
        """Build a Report from a parsed AST. Subclasses override with real logic."""

    def review_source(self, source: str, path: str = "<string>") -> Report:
        tree = ast.parse(source)  # raises SyntaxError on invalid code
        report = self.review_tree(tree, path)
        report.source = source
        return report

    def review_file(self, path: str | Path) -> Report:
        source = Path(path).read_text(encoding="utf-8")
        return self.review_source(source, str(Path(path)))


class OfflineOrchestrator(ReviewOrchestrator):
    """Runs the deterministic, local detector registry."""

    def review_tree(self, tree: ast.AST, path: str = "<string>") -> Report:
        report = Report(path=path, source="")
        report.extend(analyze(tree))
        report.dedupe()
        report.sort()
        return report


OFFLINE = OfflineOrchestrator()

__all__ = ["ReviewOrchestrator", "OfflineOrchestrator", "OFFLINE"]