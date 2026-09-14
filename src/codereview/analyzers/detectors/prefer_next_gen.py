"""PY014: manual first-item loop -> next(gen, default)."""

from __future__ import annotations

import ast

from codereview.analyzers.base import ScannerDetector
from codereview.report import Issue
from codereview.rules import PY014


class PreferNextGen(ScannerDetector):
    """Detect a manual loop that fetches the first matching item.

    **What it checks:** a `for` loop whose body is exactly `if cond: return
    x` (or `break`/`return` after capturing the first match), i.e. a loop that
    only finds the first element satisfying a predicate.

    **What it suggests:** use `next(x for x in xs if cond, default)` instead.

    **Why:** a loop whose only purpose is "give me the first match" is what
    `next()` with a generator expression expresses directly. It removes the
    manual accumulator/branch and makes the intent ("first match, or this
    default") explicit. This needs a custom scanner because the loop's meaning
    depends on the statements around it.
    """

    rule = PY014

    def _make_scanner(self) -> "_FirstFinder":
        return _FirstFinder(self.rule)


class _FirstFinder:
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def scan(self, node: ast.AST) -> None:
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                self._scan_body(value)
            elif isinstance(value, ast.AST):
                self.scan(value)

    def _scan_body(self, body: list) -> None:
        for i, stmt in enumerate(body):
            if not isinstance(stmt, ast.AST):
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor)):
                nxt = body[i + 1] if i + 1 < len(body) else None
                self._check_loop(stmt, nxt)
            self.scan(stmt)

    def _check_loop(self, node, nxt) -> None:
        if self._is_first_item_pattern(node, nxt):
            self.issues.append(self._make_issue(node))

    def _is_first_item_pattern(self, node, nxt) -> bool:
        """Loop body is `if cond: return x` (or captures first match) and the
        loop is followed by a `return` (the default)."""
        if not self._has_single_cond_return(node.body):
            return False
        return isinstance(nxt, ast.Return)

    @staticmethod
    def _has_single_cond_return(body) -> bool:
        if len(body) != 1 or not isinstance(body[0], ast.If):
            return False
        inner = body[0].body
        return (
            len(inner) == 1
            and isinstance(inner[0], ast.Return)
            and _is_item(inner[0].value)
        )

    def _make_issue(self, node: ast.For) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use next(gen, default) instead of a manual first-item loop.",
            line=node.lineno,
        )


def _is_item(value) -> bool:
    """True if the returned value is the loop item, not a constant boolean.

    `next(gen, default)` returns the *item*, so a loop that returns `True`/
    `False` (a boolean test) is an any()/all() pattern, not a first-item
    pattern. Anything else — a name, attribute, subscript, or call — is a
    plausible item and is allowed.
    """
    return not (
        isinstance(value, ast.Constant) and isinstance(value.value, bool)
    )
