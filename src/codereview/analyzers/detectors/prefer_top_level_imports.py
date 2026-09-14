"""PY016: imports inside function/method bodies.

Skips deliberate cases: imports under try: (optional deps), imports under
if TYPE_CHECKING:, and imports in test files (modules defining test_*
functions at module level) where local imports are idiomatic.
"""

from __future__ import annotations

import ast

from codereview.analyzers.base import ScannerDetector
from codereview.report import Issue
from codereview.rules import PY016

_IMPORT_TYPES = (ast.Import, ast.ImportFrom)


class PreferTopLevelImports(ScannerDetector):
    """Detect imports inside function/method bodies.

    **What it checks:** an `import`/`from ... import` statement nested inside a
    function or method body.

    **What it suggests:** move the import to the top of the module.

    **Why:** top-level imports make a module's dependencies visible at a
    glance, avoid re-importing on every call, and are the conventional
    placement. The detector deliberately skips deliberate cases: imports under
    `try:` (optional dependencies), imports under `if TYPE_CHECKING:`
    (type-only imports), and imports in test files (modules defining `test_*`
    functions at module level) where local imports are a common idiom. This
    needs a custom scanner because it must track function/try/TYPE_CHECKING
    depth while walking.
    """

    rule = PY016

    def _make_scanner(self) -> "_ImportScanner":
        return _ImportScanner(self.rule)


class _ImportScanner:
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []
        self._function_depth = 0
        self._try_depth = 0
        self._type_checking = 0
        self._is_test_file = False

    def scan(self, node: ast.AST) -> None:
        if isinstance(node, ast.Module):
            self._is_test_file = _is_test_module(node)
        self._pre(node)
        for child in ast.iter_child_nodes(node):
            self.scan(child)
        self._post(node)

    def _pre(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._function_depth += 1
        elif isinstance(node, ast.Try):
            self._try_depth += 1
        elif _is_type_checking_if(node):
            self._type_checking += 1
        elif isinstance(node, _IMPORT_TYPES):
            if (
                self._function_depth
                and not self._try_depth
                and not self._type_checking
                and not self._is_test_file
            ):
                self.issues.append(self._make_issue(node))

    def _post(self, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._function_depth -= 1
        elif isinstance(node, ast.Try):
            self._try_depth -= 1
        elif _is_type_checking_if(node):
            self._type_checking -= 1

    def _make_issue(self, node) -> Issue:
        names = ", ".join(a.asname or a.name for a in node.names)
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Import '{names}' is inside a function/method — imports are usually "
                f"clearer at the top of the file."
            ),
            line=node.lineno,
        )


def _is_type_checking_if(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def _is_test_module(tree: ast.AST) -> bool:
    """True if the module defines any test_* function at module level.

    This is the pytest convention for test files, where local imports are a
    common idiom (importing the module under test inside each test).
    """
    if not isinstance(tree, ast.Module):
        return False
    return any(
        isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name.startswith("test_")
        for stmt in tree.body
    )