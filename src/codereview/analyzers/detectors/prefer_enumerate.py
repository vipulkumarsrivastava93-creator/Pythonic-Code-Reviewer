"""PY004: range(len(x)) indexing -> enumerate."""

from __future__ import annotations

import ast

from codereview.analyzers.base import WalkDetector
from codereview.analyzers._helpers import is_call, name_of
from codereview.report import Issue
from codereview.rules import PY004


class PreferEnumerate(WalkDetector):
    """Detect `range(len(xs))` loops that index into a sequence.

    **What it checks:** a `for` loop whose iterable is `range(len(xs))` and
    whose body indexes `xs[i]` with the loop variable `i`.

    **What it suggests:** use `enumerate(xs)` and iterate `(i, x)` directly.

    **Why:** `enumerate` is the idiomatic way to get both index and value. It
    removes the manual subscript, avoids re-evaluating `len(xs)`, and reads
    more clearly — the index is a byproduct of iteration, not the driver.
    """

    rule = PY004

    def _node_issues(self, node: ast.AST) -> list[Issue]:
        if not isinstance(node, ast.For) or not self._is_range_len(node.iter):
            return []
        indexed = self._indexed_name(node)
        if not indexed:
            return []
        return [self._make_issue(node, indexed)]

    def _make_issue(self, node: ast.For, indexed: str) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Use 'enumerate({indexed})' instead of 'range(len({indexed}))' indexing.",
            line=node.lineno,
        )

    @staticmethod
    def _is_range_len(iter_node) -> bool:
        return (
            isinstance(iter_node, ast.Call)
            and is_call(iter_node, "range")
            and len(iter_node.args) == 1
            and isinstance(iter_node.args[0], ast.Call)
            and is_call(iter_node.args[0], "len")
        )

    @staticmethod
    def _indexed_name(node: ast.For) -> str | None:
        target = name_of(node.target)
        if not target:
            return None
        return next(
            (child.value.id for child in ast.walk(node) if _indexes_target(child, target)),
            None,
        )


def _indexes_target(child, target: str) -> bool:
    """True if `child` is a `xs[i]` subscript where i is `target`."""
    return (
        isinstance(child, ast.Subscript)
        and isinstance(child.value, ast.Name)
        and child.value.id != target
        and isinstance(child.slice, ast.Name)
        and child.slice.id == target
    )