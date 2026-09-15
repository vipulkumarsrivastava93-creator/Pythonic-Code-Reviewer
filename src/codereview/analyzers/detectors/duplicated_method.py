"""DES004: method bodies duplicated across classes."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES004

# A method body must have at least this many statements to be worth flagging.
MIN_METHOD_STMTS = 3


@dataclass(frozen=True)
class _Method:
    """A method (name + normalized body) belonging to a class."""

    class_name: str
    name: str
    key: str  # normalized body source
    line: int


class DuplicatedMethod(VisitorDetector):
    """Detect the same method body appearing in multiple classes.

    **What it checks:** every method in every class, keyed by its normalized
    body (names/constants stripped). Two methods in *different* classes with
    the same normalized body are duplicates — even if their names differ.

    **What it suggests:** extract a shared base class or mixin.

    **Why:** identical method bodies in different classes are copy-paste
    duplication at the class level. A shared base or mixin gives the logic one
    home, one fix point, and one place to test. The detector deliberately
    ignores `__init__` (constructors legitimately repeat boilerplate) and
    methods with fewer than 3 statements (too small to matter).
    """

    rule = DES004

    def detect(self, tree: ast.AST) -> list[Issue]:
        visitor = self._make_visitor()
        visitor.visit(tree)
        return visitor.finalize()

    def _make_visitor(self) -> "_DuplicateMethodFinder":
        return _DuplicateMethodFinder(self.rule)


class _DuplicateMethodFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []
        self._methods: list[_Method] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._methods.extend(_collect_methods(node))
        self.generic_visit(node)

    def finalize(self) -> list[Issue]:
        by_key: dict[str, list[_Method]] = {}
        for m in self._methods:
            by_key.setdefault(m.key, []).append(m)
        for group in by_key.values():
            if len(group) >= 2:
                self.issues.append(self._make_issue(group[0], group[1]))
        return self.issues

    def _make_issue(self, first: _Method, second: _Method) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Method '{first.class_name}.{first.name}' duplicates "
                f"'{second.class_name}.{second.name}'. Consider a shared base "
                f"class or mixin."
            ),
            line=first.line,
        )


def _collect_methods(cls: ast.ClassDef) -> list[_Method]:
    """Methods in `cls` with a normalized body key (duplicates eligible)."""
    methods: list[_Method] = []
    for stmt in cls.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if stmt.name == "__init__":
            continue
        body = [s for s in stmt.body if not _is_docstring(s)]
        if len(body) < MIN_METHOD_STMTS:
            continue
        key = _normalize(body)
        if not key:
            continue
        methods.append(_Method(cls.name, stmt.name, key, stmt.lineno))
    return methods


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _normalize(stmts: list[ast.stmt]) -> str:
    """Normalized source of a method body (names/constants stripped)."""
    lines: list[str] = []
    for stmt in stmts:
        try:
            src = ast.unparse(stmt)
        except Exception:  # pragma: no cover - unparse is stable on 3.9+
            return ""
        lines.append(_strip_names(src))
    return "\n".join(lines)


def _strip_names(src: str) -> str:
    """Replace identifiers and constants with placeholders, collapse spaces."""
    out: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        ch = src[i]
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (src[j].isalnum() or src[j] == "_"):
                j += 1
            out.append("N")
            i = j
        elif ch.isdigit():
            j = i
            while j < n and src[j].isdigit():
                j += 1
            out.append("C")
            i = j
        elif ch.isspace():
            out.append(" ")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip()