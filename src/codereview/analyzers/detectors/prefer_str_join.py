"""PY008: string concatenation in a loop -> str.join()."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import is_attr_call, name_of
from codereview.report import Issue
from codereview.rules import PY008


class PreferStrJoin(VisitorDetector):
    """Detect string concatenation in a loop.

    **What it checks:** a `for`/`while` loop whose body assigns `s = s + part`
    or `s += part` where `s` is a string variable.

    **What it suggests:** build a list of parts and use `"".join(parts)` (or
    `sep.join(parts)`) after the loop.

    **Why:** repeated `+`/`+=` on a string creates a new string on every
    iteration — O(n²) in the total length. `str.join` is O(n), and it makes
    the separator explicit. The detector only fires when the variable is
    definitely a string (initialized with a literal), so it does not misfire
    on numeric accumulation.
    """

    rule = PY008

    def _make_visitor(self) -> "_JoinFinder":
        return _JoinFinder(self.rule)


class _JoinFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []
        self._string_vars: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        prev = self._string_vars
        self._string_vars = set()
        self._scan_inits(node)
        self.generic_visit(node)
        self._string_vars = prev

    visit_AsyncFunctionDef = visit_FunctionDef

    def _scan_inits(self, node) -> None:
        for stmt in node.body:
            target = self._single_name_target(stmt)
            if target is not None and _is_str_literal(stmt.value):
                self._string_vars.add(target.id)

    @staticmethod
    def _single_name_target(stmt) -> ast.Name | None:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target = stmt.targets[0]
            if isinstance(target, ast.Name):
                return target
        return None

    def visit_For(self, node: ast.For) -> None:
        self._check(node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check(node)
        self.generic_visit(node)

    def _check(self, node) -> None:
        base = self._concat_base(node)
        if base is not None and base in self._string_vars:
            self.issues.append(self._make_issue(node, base))

    def _concat_base(self, node) -> str | None:
        """Return the string var being concatenated in this loop body, or None."""
        for stmt in node.body:
            if isinstance(stmt, ast.AugAssign) and isinstance(stmt.op, ast.Add):
                return name_of(stmt.target)
            if (
                isinstance(stmt, ast.Assign)
                and len(stmt.targets) == 1
                and isinstance(stmt.value, ast.BinOp)
                and isinstance(stmt.value.op, ast.Add)
            ):
                return name_of(stmt.value.left)
        return None

    def _make_issue(self, node, base: str) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Build a list of parts and use str.join instead of concatenating '{base}' in a loop.",
            line=node.lineno,
        )


def _is_str_literal(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)
