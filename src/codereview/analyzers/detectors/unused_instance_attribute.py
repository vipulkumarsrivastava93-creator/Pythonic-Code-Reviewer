"""DES007: instance attributes assigned in __init__ but never read.

Flags `self.x = ...` writes whose attribute is never read anywhere in the
class. Guards against false positives: dataclass-decorated classes, classes
that are pure data holders (no methods), and attributes that are only ever
written (e.g. caches populated lazily).
"""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES007

# Attribute names that are conventionally "write-only" (caches, lazy state).
_WRITE_ONLY_PREFIXES = ("_cache", "_lazy", "_memo")


class UnusedInstanceAttribute(VisitorDetector):
    """Detect `self.x = ...` in `__init__` where `x` is never read.

    **What it checks:** every attribute written as `self.<name> = ...` inside
    `__init__`. The attribute is "unused" if no method in the class ever
    *reads* `self.<name>` (a read is any `self.<name>` occurrence that is not
    itself a write target).

    **What it suggests:** remove the assignment, or use the attribute — dead
    instance state is misleading and usually signals a forgotten use.

    **Why:** an attribute that is written but never read is dead state. It
    misleads readers into thinking the object carries information it doesn't,
    and it is often the residue of a refactor that removed the only consumer.
    The detector deliberately skips dataclasses (fields are data, not state),
    pure data-holder classes (no methods to read them), and write-only
    attributes like caches that are populated lazily.
    """

    rule = DES007

    def _make_visitor(self) -> "_UnusedAttrFinder":
        return _UnusedAttrFinder(self.rule)


class _UnusedAttrFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if not _is_eligible(node):
            self.generic_visit(node)
            return
        written = _init_writes(node)
        if not written:
            self.generic_visit(node)
            return
        read = _class_reads(node)
        for attr, line in written:
            if attr not in read and not _is_write_only(attr):
                self.issues.append(self._make_issue(node, attr, line))
        self.generic_visit(node)

    def _make_issue(self, cls: ast.ClassDef, attr: str, line: int) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Instance attribute 'self.{attr}' is assigned in __init__ but "
                f"never read in class '{cls.name}'. Remove it or use it."
            ),
            line=line,
        )


def _is_eligible(cls: ast.ClassDef) -> bool:
    """Skip dataclasses and pure data-holder classes (no methods)."""
    if _is_dataclass_decorated(cls):
        return False
    return any(
        isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name != "__init__"
        for s in cls.body
    )


def _init_writes(cls: ast.ClassDef) -> list[tuple[str, int]]:
    """(attr, line) for every `self.<attr> = ...` write in `__init__`."""
    writes: list[tuple[str, int]] = []
    for stmt in cls.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if stmt.name != "__init__":
            continue
        writes.extend(_self_writes(stmt))
    return writes


def _self_writes(fn: ast.FunctionDef) -> list[tuple[str, int]]:
    """(attr, line) for every `self.<attr> = ...` write inside `fn`."""
    writes: list[tuple[str, int]] = []
    for node in ast.walk(fn):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        for target in _targets(node):
            if _is_self_attr(target):
                writes.append((target.attr, node.lineno))
    return writes


def _is_self_attr(node: ast.AST) -> bool:
    """True if `node` is `self.<attr>` (an attribute on the `self` name)."""
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _class_reads(cls: ast.ClassDef) -> set[str]:
    """Attribute names *read* anywhere in the class (any method).

    A `self.<attr>` occurrence counts as a read unless it is the target of an
    assignment. `self.x += 1` (AugAssign) reads `self.x`, so it counts as a
    use. Write targets are tracked by node identity so an attribute written in
    `__init__` and read in a method is correctly counted as read.
    """
    collector = _ReadCollector()
    collector.visit(cls)
    return collector.reads


class _ReadCollector(ast.NodeVisitor):
    """Collects `self.<attr>` reads, excluding assignment targets."""

    def __init__(self):
        self.reads: set[str] = set()
        self._write_targets: set[int] = set()

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._mark_write(target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._mark_write(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        # AugAssign reads its target first (`self.x += 1` uses self.x).
        self.generic_visit(node)

    def _mark_write(self, target: ast.AST) -> None:
        for node in ast.walk(target):
            if _is_self_attr(node):
                self._write_targets.add(id(node))

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if _is_self_attr(node):
            if id(node) not in self._write_targets:
                self.reads.add(node.attr)
        self.generic_visit(node)


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.AST]:
    """All assignment targets (handles tuple unpacking like `self.a, self.b = ...`)."""
    if isinstance(node, ast.Assign):
        return list(node.targets)
    return [node.target]


def _is_write_only(attr: str) -> bool:
    """True for conventionally write-only attributes (caches, lazy state)."""
    return attr.startswith(_WRITE_ONLY_PREFIXES)


def _is_dataclass_decorated(cls: ast.ClassDef) -> bool:
    """True if the class carries a @dataclass decorator (any spelling)."""
    for dec in cls.decorator_list:
        if isinstance(dec, ast.Call):
            dec = dec.func
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            return True
    return False