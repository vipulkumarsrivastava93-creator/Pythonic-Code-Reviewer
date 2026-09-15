"""DES001: classes that have grown too large to hold one responsibility."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES001

# A class body longer than this (in lines) is a candidate for splitting.
MAX_CLASS_LINES = 100


class LargeClass(VisitorDetector):
    """Detect classes whose body spans more than `MAX_CLASS_LINES` lines.

    **What it checks:** the span of a `class` body — from the first statement
    inside the class to the last one. Docstrings and blank lines are excluded
    from the count so a well-documented class isn't penalized.

    **What it suggests:** split the class — extract a mixin, a base class, or
    a collaborator — so each piece holds one responsibility.

    **Why:** a class that spans hundreds of lines is usually doing more than
    one job. Long classes are harder to read, harder to test, and tend to
    accumulate unrelated behavior. Splitting by responsibility keeps each
    class small enough to reason about in one screen.
    """

    rule = DES001

    def _make_visitor(self) -> "_LargeClassFinder":
        return _LargeClassFinder(self.rule, MAX_CLASS_LINES)


class _LargeClassFinder(ast.NodeVisitor):
    def __init__(self, rule, max_lines: int):
        self.rule = rule
        self.max_lines = max_lines
        self.issues: list[Issue] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._body_lines(node) > self.max_lines:
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    @staticmethod
    def _body_lines(node: ast.ClassDef) -> int:
        """Lines of real code in the class body (docstring/blank excluded)."""
        body = [s for s in node.body if not _is_docstring(s)]
        if not body:
            return 0
        return body[-1].end_lineno - body[0].lineno + 1

    def _make_issue(self, node: ast.ClassDef) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Class '{node.name}' spans {self._body_lines(node)} lines — "
                f"consider splitting it by responsibility."
            ),
            line=node.lineno,
        )


def _is_docstring(stmt: ast.stmt) -> bool:
    """True if `stmt` is a module/class/function docstring."""
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )