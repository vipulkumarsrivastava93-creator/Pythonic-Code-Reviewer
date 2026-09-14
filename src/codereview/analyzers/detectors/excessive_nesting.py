"""DES005: code nested more than 3 structural levels deep."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES005

_BLOCK_TYPES = (
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.If,
    ast.With,
    ast.AsyncWith,
    ast.Try,
    ast.Match,
)

MAX_DEPTH = 3


class ExcessiveNesting(VisitorDetector):
    """Detect code nested more than 3 control-flow levels deep.

    **What it checks:** a chain of control-flow blocks (`for`/`while`/`if`/
    `with`/`try`/`match`) that reaches 4 or more levels deep. `elif` chains
    are not counted as extra depth. `def` and `class` are deliberately *not*
    counted — they are scopes/namespaces, not branches, so `class → def →
    for → if` is only 2 levels of real nesting.

    **What it suggests:** extract the deeply nested portion into a method.

    **Why:** deep nesting is the strongest readability signal in Python — each
    level adds a condition the reader must hold in mind. Beyond 3 levels, the
    control flow becomes hard to follow and the function is usually doing too
    much. Extracting a method flattens the structure and names the intent.
    """

    rule = DES005

    def _make_visitor(self) -> "_DepthVisitor":
        return _DepthVisitor(self.rule, MAX_DEPTH)


class _DepthVisitor(ast.NodeVisitor):
    def __init__(self, rule, max_depth: int):
        self.rule = rule
        self.max_depth = max_depth
        self._depth = 0
        self._in_orelse = 0
        self.issues: list[Issue] = []

    def visit(self, node: ast.AST) -> None:
        is_block = isinstance(node, _BLOCK_TYPES)
        is_elif = self._in_orelse and isinstance(node, ast.If)
        if is_block and not is_elif:
            self._depth += 1
        if is_block and self._depth > self.max_depth:
            self.issues.append(self._make_issue(node))
        if isinstance(node, ast.If):
            self._in_orelse += 1
            for child in node.body:
                self.visit(child)
            self._in_orelse -= 1
            self._in_orelse += 1
            for child in node.orelse:
                self.visit(child)
            self._in_orelse -= 1
            if not is_elif:
                self._depth -= 1
            return
        for child in ast.iter_child_nodes(node):
            self.visit(child)
        if is_block and not is_elif:
            self._depth -= 1

    def _make_issue(self, node: ast.AST) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Code is nested more than {self.max_depth} levels deep "
                f"({self._depth} levels). Consider extracting a method."
            ),
            line=getattr(node, "lineno", 0),
        )