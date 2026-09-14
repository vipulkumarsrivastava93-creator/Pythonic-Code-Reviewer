"""DES006: functions defined inside other functions.

Flags non-idiomatic nested defs. Idiomatic closures — decorated functions or
functions passed as callbacks/arguments — are skipped.
"""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import name_of
from codereview.report import Issue
from codereview.rules import DES006

_FUNCTION_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_SCOPE_BOUNDARY = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


class NestedFunction(VisitorDetector):
    """Detect functions defined inside other functions.

    **What it checks:** a `def` (or `async def`) nested directly inside another
    function's body, without an intervening function/class boundary.

    **What it suggests:** hoist the inner function to module or method level.

    **Why:** a nested `def` is usually a sign the inner logic is a
    self-contained unit that deserves its own name and testability. Hoisting
    it flattens the outer function and makes the inner one reusable. The
    detector deliberately skips idiomatic closures — decorated functions and
    functions passed as callbacks/arguments — where nesting is the point.
    """

    rule = DES006

    def _make_visitor(self) -> "_NestedFinder":
        return _NestedFinder(self.rule)


class _NestedFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scan(node)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan(self, outer: ast.FunctionDef) -> None:
        passed_names = _callable_args_in(outer)
        for nested in _direct_nested_functions(outer):
            self._maybe_issue(nested, passed_names)

    def _maybe_issue(self, fn, passed_names: set[str]) -> None:
        if fn.decorator_list or fn.name in passed_names:
            return
        self.issues.append(Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Function '{fn.name}' is defined inside another function. "
                f"Consider hoisting it to module or method level."
            ),
            line=fn.lineno,
        ))


def _direct_nested_functions(outer: ast.FunctionDef) -> list[ast.AST]:
    """Functions nested inside `outer` without another function/class between."""
    found: list[ast.AST] = []
    _collect(outer, found)
    return found


def _collect(node: ast.AST, found: list[ast.AST]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _FUNCTION_TYPES):
            found.append(child)
        elif not isinstance(child, _SCOPE_BOUNDARY):
            _collect(child, found)


def _callable_args_in(outer: ast.FunctionDef) -> set[str]:
    """Names used as callable arguments (callbacks) anywhere in `outer` body."""
    names: set[str] = set()
    for node in ast.walk(outer):
        if isinstance(node, ast.Call):
            for arg in node.args:
                a = name_of(arg)
                if a:
                    names.add(a)
            for kw in node.keywords:
                val = name_of(kw.value)
                if val:
                    names.add(val)
    return names