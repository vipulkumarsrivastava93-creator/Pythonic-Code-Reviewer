"""Review orchestration: subclasses decide which reviewers run.

`ReviewOrchestrator` defines the review flow (file/source/tree parsing + report
assembly). Concrete flavors implement `review_tree`:
  - `OfflineOrchestrator` runs the deterministic, local detector registry.
  - Future `AgentOrchestrator` (LLM-backed) can extend the same base.
"""

from __future__ import annotations

import abc
import ast
import re
from pathlib import Path

from codereview.analyzers import analyze
from codereview.report import Report

# Matches `# noqa` or `# noqa: PY001, DES003` (Ruff/Flake8-style).
# Trailing explanation text after the codes is allowed, e.g.
# `# noqa: DES003 - dataclass fields, not duplicated code`.
_NOQA_RE = re.compile(r"#\s*noqa(?::\s*([A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*))?\b")


class ReviewOrchestrator(abc.ABC):
    """Base orchestrator: a review flow produces a Report from tree/source/file."""

    @abc.abstractmethod
    def review_tree(self, tree: ast.AST, path: str = "<string>") -> Report:
        """Build a Report from a parsed AST. Subclasses override with real logic."""

    def review_source(self, source: str, path: str = "<string>") -> Report:
        tree = ast.parse(source)  # raises SyntaxError on invalid code
        report = self.review_tree(tree, path)
        report.source = source
        self._apply_suppressions(report)
        return report

    def review_file(self, path: str | Path) -> Report:
        source = Path(path).read_text(encoding="utf-8")
        return self.review_source(source, str(Path(path)))

    @staticmethod
    def _apply_suppressions(report: Report) -> None:
        """Drop issues whose line carries a matching `# noqa` comment.

        Supports both bare `# noqa` (suppress everything on the line) and
        scoped `# noqa: PY001, DES003` (suppress only the listed rules).
        """
        if not report.source:
            return
        lines = report.source.splitlines()
        suppressed: set[tuple[int, str | None]] = set()
        for lineno, text in enumerate(lines, start=1):
            match = _NOQA_RE.search(text)
            if not match:
                continue
            codes = match.group(1)
            if codes:
                for code in codes.split(","):
                    suppressed.add((lineno, code.strip()))
            else:
                suppressed.add((lineno, None))
        if not suppressed:
            return
        report.issues = [
            i for i in report.issues
            if not _is_suppressed(i, suppressed)
        ]


def _is_suppressed(issue, suppressed: set[tuple[int, str | None]]) -> bool:
    """True if `issue` is covered by a `# noqa` on its line."""
    return any(
        lineno == issue.line and (code is None or code == issue.code)
        for lineno, code in suppressed
    )


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