"""PY010: manual loop testing a condition -> any()/all()."""

from __future__ import annotations

import ast

from codereview.analyzers.base import ScannerDetector
from codereview.report import Issue
from codereview.rules import PY010


class PreferAnyAll(ScannerDetector):
    """Detect a manual loop that tests a condition and returns a boolean.

    **What it checks:** a `for` loop whose body is exactly `if cond: return
    True` (or `if not cond: return False`), immediately followed by a
    `return False` (or `return True`) statement.

    **What it suggests:** replace the loop with `any(cond for x in xs)` or
    `all(cond for x in xs)`.

    **Why:** a loop whose only job is to answer "does any/all element satisfy
    this?" is exactly what `any()`/`all()` express. The builtins are
    self-documenting, short-circuit, and remove the manual accumulator. This
    needs a custom scanner because the trailing `return` is a *sibling* of the
    `for` loop, which the standard traversals do not expose.
    """

    rule = PY010

    def _make_scanner(self) -> "_LoopScanner":
        return _LoopScanner(self.rule)


class _LoopScanner:
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def scan(self, node: ast.AST) -> None:
        # Visit each child exactly once via its parent's fields, so a `for` is
        # never checked twice. Some fields hold plain values (e.g. `Global.names`
        # is a list of str) — only recurse into real AST nodes.
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                self._scan_body(value)
            elif isinstance(value, ast.AST):
                self.scan(value)

    def _scan_body(self, body: list) -> None:
        """Scan a statement list, pairing each `for` with its following sibling."""
        for i, stmt in enumerate(body):
            if not isinstance(stmt, ast.AST):
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor)):
                nxt = body[i + 1] if i + 1 < len(body) else None
                self._check_loop(stmt, nxt)
            self.scan(stmt)

    def _check_loop(self, node, nxt) -> None:
        if self._is_any_pattern(node, nxt):
            self.issues.append(self._make_issue(node, "any"))
        elif self._is_all_pattern(node, nxt):
            self.issues.append(self._make_issue(node, "all"))

    def _is_any_pattern(self, node, nxt) -> bool:
        """`for x in xs: if cond: return True` followed by `return False`."""
        return (
            _is_single_if_return(node.body, True)
            and isinstance(nxt, ast.Return)
            and _is_false(nxt.value)
        )

    def _is_all_pattern(self, node, nxt) -> bool:
        """`for x in xs: if not cond: return False` followed by `return True`."""
        return (
            _is_single_if_return(node.body, False)
            and isinstance(nxt, ast.Return)
            and _is_true(nxt.value)
        )

    def _make_issue(self, node: ast.For, which: str) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Use {which}() instead of a manual loop to test a condition.",
            line=node.lineno,
        )


def _is_single_if_return(body, value: bool) -> bool:
    """True if `body` is exactly `if cond: return <value>` (no else)."""
    if len(body) != 1 or not isinstance(body[0], ast.If):
        return False
    if body[0].orelse:
        return False
    inner = body[0].body
    if len(inner) != 1 or not isinstance(inner[0], ast.Return):
        return False
    return _is_true(inner[0].value) if value else _is_false(inner[0].value)


def _is_true(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is False