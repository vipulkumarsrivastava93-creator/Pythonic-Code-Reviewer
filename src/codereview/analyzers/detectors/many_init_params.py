"""DES002: __init__ methods with too many parameters."""

from __future__ import annotations

import ast

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES002

# More than this many parameters (excluding self) is a smell.
MAX_INIT_PARAMS = 5


class ManyInitParams(VisitorDetector):
    """Detect `__init__` methods with more than `MAX_INIT_PARAMS` parameters.

    **What it checks:** the parameter list of every `__init__` method. `self`
    is excluded; `*args`/`**kwargs` are counted as one parameter each.

    **What it suggests:** bundle related parameters into a config object or
    dataclass, or split the class.

    **Why:** a constructor with many parameters is a strong signal that the
    class takes on too many responsibilities or that its inputs should be
    grouped. Long parameter lists are hard to call correctly, easy to get in
    the wrong order, and painful to extend.
    """

    rule = DES002

    def _make_visitor(self) -> "_InitParamCounter":
        return _InitParamCounter(self.rule, MAX_INIT_PARAMS)


class _InitParamCounter(ast.NodeVisitor):
    def __init__(self, rule, max_params: int):
        self.rule = rule
        self.max_params = max_params
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "__init__":
            count = _param_count(node)
            if count > self.max_params:
                self.issues.append(self._make_issue(node, count))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def _make_issue(self, node: ast.FunctionDef, count: int) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"__init__ has {count} parameters (max {self.max_params}). "
                f"Consider a config object or dataclass."
            ),
            line=node.lineno,
        )


def _param_count(node: ast.FunctionDef) -> int:
    """Number of parameters, excluding `self`/`cls`; *args/**kwargs count as 1."""
    args = node.args
    count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    if args.vararg is not None:
        count += 1
    if args.kwarg is not None:
        count += 1
    if count and args.args and args.args[0].arg in ("self", "cls"):
        count -= 1
    return count