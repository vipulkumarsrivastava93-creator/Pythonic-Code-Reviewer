"""Structural graph builders: extract AST facts for the codebase index.

Pure functions that read a `.py` file once and return the facts the
`CodebaseIndex` needs: what modules it imports, what classes it defines and
their bases, and how its path maps to a dotted module name.
"""

from __future__ import annotations

import ast
from pathlib import Path


def import_names(path: Path) -> set[str]:
    """Dotted module names imported by a file (e.g. 'os', 'codereview.report').

    Relative imports (`from . import x`) are skipped — they cannot be
    resolved to a module name without the package context.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import
                continue
            if node.module:
                names.add(node.module)
    return names


def module_name(rel: str) -> str:
    """Indexed file path -> dotted module name.

    'codereview/analyzers/__init__.py' -> 'codereview.analyzers'
    'codereview/report.py'            -> 'codereview.report'
    """
    p = rel.replace("\\", "/")
    if p.endswith("/__init__.py"):
        return p[: -len("/__init__.py")].replace("/", ".")
    return p[: -len(".py")].replace("/", ".")


def class_bases(path: Path) -> dict[str, set[str]]:
    """Map class name -> base class names for every class in a file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    result: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases: set[str] = set()
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.add(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.add(base.attr)
            if bases:
                result[node.name] = bases
    return result