"""PY009: manual dict init-then-append -> defaultdict/list or Counter."""

from __future__ import annotations

import ast

from codereview.analyzers.base import WalkDetector
from codereview.analyzers._helpers import is_attr_call, name_of
from codereview.report import Issue
from codereview.rules import PY009


class PreferDefaultdict(WalkDetector):
    """Detect manual dict init-then-append aggregation.

    **What it checks:** an `if key in d:` guard whose body appends to `d[key]`
    and whose `else` initializes `d[key] = [value]`.

    **What it suggests:** use `collections.defaultdict(list)` (or `Counter`)
    and drop the membership check entirely.

    **Why:** the init-then-append dance is boilerplate that `defaultdict`
    eliminates. The intent — "append to the list for this key, creating it if
    missing" — is stated once, not spelled out in two branches.
    """

    rule = PY009

    def _node_issues(self, node: ast.AST) -> list[Issue]:
        if not isinstance(node, ast.If) or not self._is_init_then_append(node):
            return []
        return [self._make_issue(node)]

    def _make_issue(self, node: ast.If) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use collections.defaultdict(list) instead of manual init-then-append aggregation.",
            line=node.lineno,
        )

    def _is_init_then_append(self, node: ast.If) -> bool:
        key, target = self._in_membership(node)
        if not (key and target):
            return False
        if not self._is_single_append(node.body, "append"):
            return False
        return self._is_single_assign_list(node.orelse)

    @staticmethod
    def _in_membership(node: ast.If) -> tuple[str | None, str | None]:
        test = node.test
        if not (isinstance(test, ast.Compare) and test.ops and isinstance(test.ops[0], ast.In)):
            return None, None
        return name_of(test.comparators[0]), name_of(test.left)

    @staticmethod
    def _is_single_append(stmts, which: str) -> bool:
        return len(stmts) == 1 and isinstance(stmts[0], ast.Expr) and is_attr_call(stmts[0].value, which)

    @staticmethod
    def _is_single_assign_list(stmts) -> bool:
        return len(stmts) == 1 and isinstance(stmts[0], ast.Assign)