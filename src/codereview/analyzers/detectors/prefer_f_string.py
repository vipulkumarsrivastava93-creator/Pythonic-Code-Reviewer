"""PY002: manual string concatenation -> f-string."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import PY002


class PreferFString(VisitorDetector):
    """Detect manual string concatenation that mixes literals and variables.

    **What it checks:** a `+` `BinOp` where at least one side is a string
    literal and the other is a non-literal expression (a variable, call, etc.).

    **What it suggests:** use an f-string instead.

    **Why:** f-strings are the modern, readable way to interpolate values into
    text. Concatenating `"Hello, " + name` forces the reader to mentally
    reassemble the pieces; `f"Hello, {name}"` shows the whole string at once.
    The detector skips `"a" + "b"` (two literals) — that's a constant fold,
    not an interpolation, and rewriting it adds nothing.
    """

    rule = PY002

    def _make_visitor(self) -> "_ConcatFinder":
        return _ConcatFinder(self.rule)


class _ConcatFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if self._is_string_concat(node):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    def _is_string_concat(self, node: ast.BinOp) -> bool:
        """True for `a + b` where at least one side is a string literal and the
        other is a non-literal expression (i.e. involves a variable).

        Skips `"a" + "b"` (two literals) per the rule guard.
        """
        if not isinstance(node.op, ast.Add):
            return False
        left, right = node.left, node.right
        left_lit = _is_str_literal(left)
        right_lit = _is_str_literal(right)
        if not (left_lit or right_lit):
            return False
        # At least one side must be a real expression, not just two literals.
        return not (left_lit and right_lit)

    def _make_issue(self, node: ast.BinOp) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use an f-string instead of manual string concatenation.",
            line=node.lineno,
        )


def _is_str_literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)
