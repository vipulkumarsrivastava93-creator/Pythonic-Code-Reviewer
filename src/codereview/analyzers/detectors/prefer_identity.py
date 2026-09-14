"""PY007: == None / != None -> is None / is not None."""

from __future__ import annotations

import ast

from codereview.analyzers.base import WalkDetector
from codereview.analyzers._helpers import is_none_constant
from codereview.report import Issue
from codereview.rules import PY007


class PreferIdentity(WalkDetector):
    """Detect `== None` / `!= None` comparisons.

    **What it checks:** any `Compare` node whose operator is `==` or `!=` and
    whose comparator is the `None` literal.

    **What it suggests:** use `is None` / `is not None` instead.

    **Why:** `None` is a singleton, so identity comparison is both faster and
    more explicit about intent. `==` can be overloaded by a custom `__eq__`,
    which can make `x == None` behave unexpectedly; `is None` is unambiguous.
    """

    rule = PY007

    def _node_issues(self, node: ast.AST) -> list[Issue]:
        if not isinstance(node, ast.Compare):
            return []
        return [
            self._make_issue(node)
            for op, comp in zip(node.ops, node.comparators)
            if isinstance(op, (ast.Eq, ast.NotEq)) and is_none_constant(comp)
        ]

    def _make_issue(self, node: ast.Compare) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use 'is None'/'is not None' instead of '== None'/'!= None'.",
            line=node.lineno,
        )