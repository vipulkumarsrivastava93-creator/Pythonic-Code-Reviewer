"""PY006: 'if key in dict' then subscript -> dict.get()."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import name_of
from codereview.report import Issue
from codereview.rules import PY006


class PreferDictGet(VisitorDetector):
    """Detect `if key in d:` followed by a `d[key]` subscript.

    **What it checks:** an `if key in d:` guard (no `else`) whose body
    subscripts `d[key]` with the same key.

    **What it suggests:** use `d.get(key)` (with a default if needed).

    **Why:** the membership check plus subscript is two lookups doing the work
    of one. `dict.get` expresses "fetch this key, with a fallback" directly,
    and avoids the double lookup and the extra branch. The detector only fires
    when there is no `else`, because an `else` branch usually means the
    presence/absence distinction matters and `get` would not be a clean fit.
    """

    rule = PY006

    def _make_visitor(self) -> "_GetFinder":
        return _GetFinder(self.rule)


class _GetFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_If(self, node: ast.If) -> None:
        if self._is_get_pattern(node):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    def _is_get_pattern(self, node: ast.If) -> bool:
        """Match `if key in d: ... d[key] ...` (no else)."""
        if node.orelse:
            return False
        container, key = self._in_membership(node)
        if not (container and key):
            return False
        return _uses_subscript(node.body, container, key)

    @staticmethod
    def _in_membership(node: ast.If) -> tuple[str | None, str | None]:
        test = node.test
        if not (isinstance(test, ast.Compare) and test.ops and isinstance(test.ops[0], ast.In)):
            return None, None
        return name_of(test.comparators[0]), name_of(test.left)

    def _make_issue(self, node: ast.If) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use dict.get() instead of 'if key in dict' then subscript.",
            line=node.lineno,
        )


def _uses_subscript(stmts, target: str, key: str) -> bool:
    """True if any statement subscripts `target[key]`."""
    for stmt in stmts:
        for node in ast.walk(stmt):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id == target
                and isinstance(node.slice, ast.Name)
                and node.slice.id == key
            ):
                return True
    return False
