"""Shared AST-recognition predicates used by detectors (no state, no IO)."""

from __future__ import annotations

import ast


def name_of(node) -> str | None:
    """Best-effort name of a Name/Attribute node (e.g. 'result' from result.append)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def is_call(node, func_name: str) -> bool:
    """True if node is a Call to a function named func_name."""
    return isinstance(node, ast.Call) and name_of(node.func) == func_name


def is_attr_call(node, attr_name: str) -> bool:
    """True if node is a Call whose func is Some.value.attr_name(...)."""
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attr_name


def is_none_constant(node) -> bool:
    """True if node is the None literal."""
    return isinstance(node, ast.Constant) and node.value is None