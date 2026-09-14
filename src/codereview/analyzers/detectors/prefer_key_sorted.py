"""PY013: manual comparison key -> key= on sorted/max/min."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import is_attr_call
from codereview.report import Issue
from codereview.rules import PY013

_SORT_CALLS = ("sorted", "max", "min", "list.sort")


class PreferKeySorted(VisitorDetector):
    """Detect a manual comparison function passed to sorted/max/min.

    **What it checks:** a call to `sorted`/`max`/`min`/`list.sort` whose
    comparison argument is a lambda of the form `lambda a, b: a.attr < b.attr`
    (or similar), i.e. a manual two-argument comparator.

    **What it suggests:** use the `key=` argument with a one-argument accessor
    instead, e.g. `sorted(xs, key=lambda x: x.attr)`.

    **Why:** a two-argument comparator re-implements ordering that the `key=`
    transformation expresses directly. `key=` is faster (it computes the key
    once per element instead of pairwise) and more readable. A plain
    one-argument key lambda is already idiomatic and is left alone.
    """

    rule = PY013

    def _make_visitor(self) -> "_KeyFinder":
        return _KeyFinder(self.rule)


class _KeyFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_Call(self, node: ast.Call) -> None:
        if self._is_manual_comparator(node):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    @staticmethod
    def _is_manual_comparator(node: ast.Call) -> bool:
        func = node.func
        if not isinstance(func, ast.Name) and not is_attr_call(node, "sort"):
            return False
        if is_attr_call(node, "sort"):
            name = "list.sort"
        else:
            assert isinstance(func, ast.Name)
            name = func.id
        if name not in _SORT_CALLS:
            return False
        return any(isinstance(arg, ast.Lambda) and _has_two_args(arg) for arg in node.args)

    def _make_issue(self, node: ast.Call) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use key= with sorted()/max()/min() instead of a manual comparison lambda.",
            line=node.lineno,
        )


def _has_two_args(lambda_node: ast.Lambda) -> bool:
    return len(lambda_node.args.args) == 2
