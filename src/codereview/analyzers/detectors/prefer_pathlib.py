"""PY011: os.path string manipulation -> pathlib.Path."""

from __future__ import annotations

import ast

from codereview.analyzers.base import WalkDetector
from codereview.analyzers._helpers import is_attr_call, name_of
from codereview.report import Issue
from codereview.rules import PY011

_OS_PATH_FUNCS = {
    "join", "basename", "dirname", "splitext", "exists", "isfile", "isdir",
    "normpath", "abspath", "relpath", "realpath", "expanduser",
}


class PreferPathlib(WalkDetector):
    """Detect `os.path` string manipulation calls.

    **What it checks:** a call to an `os.path.*` function (join, basename,
    dirname, splitext, exists, isfile, isdir, ...) such as `os.path.join(a, b)`.

    **What it suggests:** use the corresponding `pathlib.Path` API instead
    (e.g. `Path(a) / b`, `path.name`, `path.exists()`).

    **Why:** `pathlib` represents paths as objects with methods rather than
    raw strings, which is more readable, composable, and cross-platform.
    String-based `os.path` code strings paths together and misses the
    structure of a filesystem path. This is a `WalkDetector` because the smell
    is visible in the node itself — no parent/scope context is needed.
    """

    rule = PY011

    def _node_issues(self, node: ast.AST) -> list[Issue]:
        if not self._is_os_path_call(node):
            return []
        return [self._make_issue(node)]

    @staticmethod
    def _is_os_path_call(node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr in _OS_PATH_FUNCS):
            return False
        value = func.value
        return isinstance(value, ast.Attribute) and value.attr == "path"

    def _make_issue(self, node: ast.Call) -> Issue:
        func = node.func
        assert isinstance(func, ast.Attribute)
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Use pathlib.Path instead of os.path.{func.attr}(...) — "
                f"e.g. path.{self._pathlib_name(func.attr)}."
            ),
            line=node.lineno,
        )

    @staticmethod
    def _pathlib_name(os_func: str) -> str:
        return {
            "join": "/", "basename": "name", "dirname": "parent", "splitext": "suffix",
        }.get(os_func, f"{os_func}()")
