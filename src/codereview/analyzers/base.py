"""Shared base + registry for code-review detectors."""

from __future__ import annotations

import abc
import ast
from typing import ClassVar

from codereview.report import Issue
from codereview.rules import Rule


class Detector(abc.ABC):
    """Base class for all detectors.

    A detector inspects a parsed AST and reports `Issue`s. Subclasses set
    `rule` (the registry entry they implement) and pick a traversal base
    (`WalkDetector`, `VisitorDetector`, or `ScannerDetector`) that matches
    how much context they need.

    Every detector docstring should state:
      - **What it checks** — the AST pattern it looks for.
      - **What it suggests** — the idiomatic replacement it recommends.
      - **Why** — the readability/maintainability rationale.
    """

    rule: ClassVar[Rule]

    @abc.abstractmethod
    def detect(self, tree: ast.AST) -> list[Issue]:
        """Return issues detected in `tree`."""


class WalkDetector(Detector):
    """Detector that inspects each node independently via `ast.walk`.

    **What it checks:** every node in the tree in isolation — no parent,
    sibling, or scope context is needed to decide whether a node is a problem.
    Subclasses implement `_node_issues(node)`.

    **What it suggests:** whatever the subclass's rule prescribes.

    **Why:** `ast.walk` is the simplest traversal. Use it when a node can be
    judged purely by its own shape (e.g. `x == None` is always an identity
    smell). Order is not guaranteed by `ast.walk`, so callers that need
    line-sorted output should sort afterwards (the orchestrator already does).
    """

    def detect(self, tree: ast.AST) -> list[Issue]:
        issues: list[Issue] = []
        for node in ast.walk(tree):
            issues.extend(self._node_issues(node))
        return issues

    @abc.abstractmethod
    def _node_issues(self, node: ast.AST) -> list[Issue]:
        """Return issues for a single node."""


class VisitorDetector(Detector):
    """Detector that traverses with a stateful `ast.NodeVisitor`.

    **What it checks:** nodes that need *accumulated state* to judge — e.g.
    which lists were initialized earlier in a scope, or how deep the current
    nesting is. Subclasses implement `_make_visitor()` returning a visitor
    that collects issues into `visitor.issues`.

    **What it suggests:** whatever the subclass's rule prescribes.

    **Why:** `NodeVisitor` gives depth-first, in-order traversal with mutable
    state, which is needed when a node's meaning depends on what came before
    it. `detect()` creates a fresh visitor per tree so state never leaks
    between calls.
    """

    def detect(self, tree: ast.AST) -> list[Issue]:
        visitor = self._make_visitor()
        visitor.visit(tree)
        return visitor.issues

    @abc.abstractmethod
    def _make_visitor(self) -> "ast.NodeVisitor":
        """Return a fresh visitor for one tree."""


class ScannerDetector(Detector):
    """Detector that needs custom traversal (sibling/ancestor context).

    **What it checks:** patterns that `ast.walk` and `NodeVisitor` cannot
    express — e.g. a `for` loop paired with the *following* statement, or an
    import's position relative to enclosing `try:`/`TYPE_CHECKING` blocks.
    Subclasses implement `_make_scanner()` returning a scanner that collects
    issues into `scanner.issues`.

    **What it suggests:** whatever the subclass's rule prescribes.

    **Why:** some rules need sibling or ancestor context that the standard
    traversals hide. A hand-written `scan()` gives full control over the walk
    while keeping the `detect()` entry point uniform. `detect()` creates a
    fresh scanner per tree.
    """

    def detect(self, tree: ast.AST) -> list[Issue]:
        scanner = self._make_scanner()
        scanner.scan(tree)
        return scanner.issues

    @abc.abstractmethod
    def _make_scanner(self) -> "ScannerDetector":
        """Return a fresh scanner for one tree."""