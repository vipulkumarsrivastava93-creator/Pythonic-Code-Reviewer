"""PY003: bare open() without a context manager -> with open(...)."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.analyzers._helpers import is_call
from codereview.report import Issue
from codereview.rules import PY003


class PreferWithOpen(VisitorDetector):
    """Detect bare `open()` calls not guarded by a context manager.

    **What it checks:** any `open(...)` call that is not inside a `with`
    statement (the visitor does not descend into `with` bodies, so managed
    opens are never flagged).

    **What it suggests:** use `with open(...) as f:`.

    **Why:** a bare `open()` leaves the file handle to the caller to close,
    and an early return or exception can leak it. The `with` statement
    guarantees the file is closed when the block exits, making resource
    lifetime explicit and exception-safe.
    """

    rule = PY003

    def _make_visitor(self) -> "_OpenFinder":
        return _OpenFinder(self.rule)


class _OpenFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_With(self, node: ast.With) -> None:
        # Don't descend into `with open(...)` bodies: the open is already managed.
        return

    visit_AsyncWith = visit_With

    def visit_Call(self, node: ast.Call) -> None:
        if is_call(node, "open"):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    def _make_issue(self, node: ast.Call) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message="Use 'with open(...)' instead of calling open() without closing.",
            line=node.lineno,
        )
