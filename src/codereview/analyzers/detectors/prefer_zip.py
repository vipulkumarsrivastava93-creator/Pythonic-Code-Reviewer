"""PY005: parallel iteration via range(len(...)) indexing -> zip."""

from __future__ import annotations

import ast

from codereview.analyzers.base import WalkDetector
from codereview.analyzers._helpers import is_call, name_of
from codereview.report import Issue
from codereview.rules import PY005


class PreferZip(WalkDetector):
    """Detect parallel iteration via `range(len(...))` indexing.

    **What it checks:** a `for` loop over `range(len(xs))` whose body indexes
    **two or more** distinct sequences with the loop variable (e.g. `xs[i]`
    and `ys[i]`).

    **What it suggests:** use `zip(xs, ys)` and iterate the pairs directly.

    **Why:** indexing two sequences by a shared index is exactly what `zip`
    expresses. It removes the manual subscripting, guarantees the sequences
    are paired element-wise, and reads as "iterate these together" rather than
    "drive everything by this index."
    """

    rule = PY005

    def _node_issues(self, node: ast.AST) -> list[Issue]:
        if not isinstance(node, ast.For):
            return []
        indexed = self._parallel_indexed(node)
        if not indexed:
            return []
        return [self._make_issue(node, indexed)]

    def _make_issue(self, node: ast.For, indexed: list[str]) -> Issue:
        names = ", ".join(indexed)
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Use zip({names}) to iterate these sequences in parallel.",
            line=node.lineno,
        )

    def _parallel_indexed(self, node: ast.For) -> list[str]:
        """Return the distinct sequences indexed by the loop variable, if the
        loop iterates `range(len(...))` and indexes more than one sequence.
        """
        if not _is_range_len(node.iter):
            return []
        index = name_of(node.target)
        if not index:
            return []
        sequences: list[str] = []
        for child in ast.walk(node):
            seq = _indexed_sequence(child, index)
            if seq and seq not in sequences:
                sequences.append(seq)
        return sequences if len(sequences) >= 2 else []


def _is_range_len(iter_node) -> bool:
    return (
        isinstance(iter_node, ast.Call)
        and is_call(iter_node, "range")
        and len(iter_node.args) == 1
        and isinstance(iter_node.args[0], ast.Call)
        and is_call(iter_node.args[0], "len")
    )


def _indexed_sequence(child, index: str) -> str | None:
    """Return the sequence name for `seq[index]`, or None."""
    if (
        isinstance(child, ast.Subscript)
        and isinstance(child.value, ast.Name)
        and isinstance(child.slice, ast.Name)
        and child.slice.id == index
    ):
        return child.value.id
    return None
