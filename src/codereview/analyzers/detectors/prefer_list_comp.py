"""PY001: manual append-loop -> list comprehension."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import is_attr_call, name_of
from codereview.report import Issue
from codereview.rules import PY001


class PreferListComprehension(VisitorDetector):
    """Detect a manual append-loop that builds a list.

    **What it checks:** a `for` loop whose body is a single `result.append(x)`
    call, where `result` was initialized to `[]` earlier in the same scope.

    **What it suggests:** replace the loop with a list comprehension
    `[x for ... in ...]`.

    **Why:** building a list by appending in a loop is the classic
    comprehension candidate. A comprehension states the transformation in one
    expression, is faster, and avoids the mutable accumulator. The detector
    deliberately skips loops whose append argument has side effects (a call,
    await, or yield) — those cannot be safely rewritten.
    """

    rule = PY001

    def _make_visitor(self) -> "_AppendLoop":
        return _AppendLoop(self.rule)


class _AppendLoop(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []
        self._known_lists: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self._known_lists
        self._known_lists = set()
        self._scan_inits(node)
        self.generic_visit(node)
        self._known_lists = prev

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan_inits(self, node) -> None:
        for stmt in node.body:
            target = self._single_name_target(stmt)
            if target is not None and _is_list_init(stmt.value):
                self._known_lists.add(target.id)

    @staticmethod
    def _single_name_target(stmt) -> ast.Name | None:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                return target
        return None

    def visit_For(self, node: ast.For) -> None:
        base = self._append_base(node)
        if base is not None and base in self._known_lists:
            self._record(node, base)
        self.generic_visit(node)

    def _append_base(self, node: ast.For) -> str | None:
        if len(node.body) != 1:
            return None
        stmt = node.body[0]
        if not isinstance(stmt, ast.Expr):
            return None
        call = stmt.value
        if not is_attr_call(call, "append"):
            return None
        arg = call.args[0] if call.args else None
        if arg is None or _is_effectful(arg):
            return None
        assert isinstance(call.func, ast.Attribute), "append is an attribute call"
        return name_of(call.func.value)

    def _record(self, node: ast.For, base: str) -> None:
        self.issues.append(Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Consider a list comprehension instead of appending to '{base}' in a loop.",
            line=node.lineno,
        ))


def _is_list_init(value) -> bool:
    return isinstance(value, ast.List) and not value.elts or isinstance(value, ast.ListComp)


def _is_effectful(arg) -> bool:
    return any(isinstance(arg, t) for t in (ast.Call, ast.Await, ast.Yield))