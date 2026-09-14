"""PY012: attribute-heavy class -> dataclasses.dataclass."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import PY012

_ATTR_INIT_STMTS = (ast.Assign, ast.AnnAssign)


class PreferDataclass(VisitorDetector):
    """Detect a class that is mostly data (attributes, no methods).

    **What it checks:** a `class` body consisting mainly of attribute
    assignments (including annotated ones) with few or no methods.

    **What it suggests:** decorate it with `@dataclasses.dataclass` (or use
    another data-class tool like a NamedTuple).

    **Why:** a class that exists only to hold data is exactly what a dataclass
    is for: it auto-generates `__init__`, `__repr__`, `__eq__`, and more,
    removing boilerplate. A class with real methods, or with non-field logic,
    is not a good dataclass candidate — the detector leaves those alone.
    """

    rule = PY012

    def _make_visitor(self) -> "_DataClassFinder":
        return _DataClassFinder(self.rule)


class _DataClassFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if self._is_data_class(node):
            self.issues.append(self._make_issue(node))
        self.generic_visit(node)

    @staticmethod
    def _is_data_class(node: ast.ClassDef) -> bool:
        if _is_dataclass_decorated(node):
            return False
        attrs = 0
        methods = 0
        for stmt in node.body:
            if isinstance(stmt, _ATTR_INIT_STMTS):
                attrs += 1
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods += 1
        return attrs >= 2 and methods == 0

    def _make_issue(self, node: ast.ClassDef) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=f"Class '{node.name}' holds only attributes — consider dataclasses.dataclass.",
            line=node.lineno,
        )


def _is_dataclass_decorated(node: ast.ClassDef) -> bool:
    """True if the class already carries a @dataclass decorator.

    Handles all three spellings: `@dataclass`, `@dataclasses.dataclass`, and
    `@dataclass(frozen=True)` (a Call whose func is one of the first two).
    """
    for dec in node.decorator_list:
        if isinstance(dec, ast.Call):
            dec = dec.func
        if isinstance(dec, ast.Name) and dec.id == "dataclass":
            return True
        if isinstance(dec, ast.Attribute) and dec.attr == "dataclass":
            return True
    return False
