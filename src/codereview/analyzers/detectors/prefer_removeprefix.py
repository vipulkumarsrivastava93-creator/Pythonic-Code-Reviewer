"""PY015: manual prefix/suffix slicing -> str.removeprefix/removesuffix."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import PY015


class PreferRemovePrefix(VisitorDetector):
    """Detect manual prefix/suffix slicing on a string.

    **What it checks:** a slice expression on a string variable whose length is
    derived from the variable itself — e.g. `s[len(prefix):]` (remove prefix)
    or `s[:-len(suffix)]` (remove suffix).

    **What it suggests:** use `s.removeprefix(prefix)` / `s.removesuffix(suffix)`
    (Python 3.9+).

    **Why:** manual slicing `s[len(p):]` obscures intent (you must read it to
    realize it strips a prefix) and is easy to get wrong. `removeprefix`/
    `removesuffix` say exactly what they do and handle the "not present"
    case gracefully. The detector only fires when the slice endpoints are
    derived from the same string, so it never misfires on general indexing.
    """

    rule = PY015

    def _make_visitor(self) -> "_SliceFinder":
        return _SliceFinder(self.rule)


class _SliceFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if self._is_prefix_slice(node) or self._is_suffix_slice(node):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    @staticmethod
    def _is_prefix_slice(node: ast.Subscript) -> bool:
        """Match `s[len(prefix):]`."""
        sl = node.slice
        if not isinstance(sl, ast.Slice):
            return False
        if sl.step is not None or sl.upper is not None:
            return False
        return _is_len_of_name(sl.lower) and isinstance(node.value, ast.Name)

    @staticmethod
    def _is_suffix_slice(node: ast.Subscript) -> bool:
        """Match `s[:-len(suffix)]`."""
        sl = node.slice
        if not isinstance(sl, ast.Slice):
            return False
        if sl.step is not None or sl.lower is not None or sl.upper is None:
            return False
        upper = sl.upper
        return (
            isinstance(upper, ast.UnaryOp)
            and isinstance(upper.op, ast.USub)
            and _is_len_of_name(upper.operand)
            and isinstance(node.value, ast.Name)
        )

    def _make_issue(self, node: ast.Subscript) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use str.removeprefix()/str.removesuffix() instead of manual slicing (3.9+).",
            line=node.lineno,
        )


def _is_len_of_name(node) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len" and bool(node.args) and isinstance(node.args[0], ast.Name)
