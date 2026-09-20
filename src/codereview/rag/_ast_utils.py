"""Shared AST utilities for the RAG chunker (pure functions, no state)."""

from __future__ import annotations

import ast


def name_of(node: ast.AST | None) -> str | None:
    """Best-effort name of a Name/Attribute node (e.g. 'VisitorDetector')."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def format_args(args: ast.arguments) -> str:
    """Render a function's positional args as 'a, b, c' (no defaults/types)."""
    names = [a.arg for a in args.posonlyargs + args.args]
    if args.vararg:
        names.append(f"*{args.vararg.arg}")
    if args.kwonlyargs:
        names.append("*")
        names.extend(a.arg for a in args.kwonlyargs)
    if args.kwarg:
        names.append(f"**{args.kwarg.arg}")
    return ", ".join(names)


def first_docstring_line(node: ast.AST) -> str:
    """First line of a node's docstring, or ''."""
    body = getattr(node, "body", None)
    if not body:
        return ""
    first = body[0]
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
            and isinstance(first.value.value, str):
        return first.value.value.strip().splitlines()[0] if first.value.value else ""
    return ""


def assign_targets(stmt: ast.Assign | ast.AnnAssign) -> list[str]:
    """Names assigned by an Assign/AnnAssign statement."""
    if isinstance(stmt, ast.AnnAssign):
        return [name_of(stmt.target)]
    return [name_of(t) for t in stmt.targets]