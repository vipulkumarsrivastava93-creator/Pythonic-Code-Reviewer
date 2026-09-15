"""DES003: duplicated code blocks within the same scope."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from codereview.analyzers.base import VisitorDetector
from codereview.report import Issue
from codereview.rules import DES003

# A block must have at least this many statements to be worth flagging.
MIN_BLOCK_STMTS = 3


@dataclass(frozen=True)
class _Block:
    """A run of consecutive statements inside one scope."""

    stmts: tuple[ast.stmt, ...]
    key: str  # normalized source of the run

    @property
    def line(self) -> int:
        return self.stmts[0].lineno

    @property
    def end_line(self) -> int:
        return self.stmts[-1].end_lineno


class DuplicatedBlock(VisitorDetector):
    """Detect repeated runs of statements inside the same function/class body.

    **What it checks:** every window of `MIN_BLOCK_STMTS` consecutive
    statements in a function or class body, normalized (names/constants
    stripped), compared against every other window in the same scope. Two
    windows whose normalized source matches are duplicates.

    **What it suggests:** extract the repeated block into a helper function.

    **Why:** copy-pasted blocks are the most common source of drift — a fix
    applied to one copy is forgotten in the other. Extracting a helper gives
    the repeated logic one home and one place to test.
    """

    rule = DES003

    def detect(self, tree: ast.AST) -> list[Issue]:
        visitor = self._make_visitor()
        visitor.visit(tree)
        return visitor.issues

    def _make_visitor(self) -> "_DuplicateBlockFinder":
        return _DuplicateBlockFinder(self.rule)


class _DuplicateBlockFinder(ast.NodeVisitor):
    def __init__(self, rule):
        self.rule = rule
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scan_scope(node.body)
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scan_scope(_class_statements(node))
        self.generic_visit(node)

    def _scan_scope(self, body: list[ast.stmt]) -> None:
        """Emit one issue per duplicated block pattern in this scope."""
        by_key: dict[str, list[_Block]] = {}
        for run in _collect_runs(body):
            for block in _windows(run):
                group = by_key.setdefault(block.key, [])
                if not any(_overlaps(block, other) for other in group):
                    group.append(block)
        for group in by_key.values():
            if len(group) >= 2:
                self.issues.append(self._make_issue(group[0], group[1]))

    def _make_issue(self, first: _Block, second: _Block) -> Issue:
        return Issue(
            code=self.rule.code,
            category=self.rule.category,
            severity=self.rule.severity,
            message=(
                f"Block at line {first.line} repeats code at line {second.line}. "
                f"Consider extracting a helper."
            ),
            line=first.line,
            end_line=first.end_line,
        )


def _collect_runs(body: list[ast.stmt]) -> list[list[ast.stmt]]:
    """Maximal runs of consecutive duplicable statements in `body`.

    A run is a maximal sequence of duplicable statements (assignments,
    expressions). Runs are split at non-duplicable statements (if/for/return),
    so two separate 3-statement blocks are compared independently.
    """
    runs: list[list[ast.stmt]] = []
    run: list[ast.stmt] = []
    for stmt in body:
        if _is_docstring(stmt):
            continue
        if _is_duplicable(stmt):
            run.append(stmt)
        else:
            if len(run) >= MIN_BLOCK_STMTS:
                runs.append(run)
            run = []
    if len(run) >= MIN_BLOCK_STMTS:
        runs.append(run)
    return runs


def _class_statements(cls: ast.ClassDef) -> list[ast.stmt]:
    """Class body plus all method bodies, flattened into one scope."""
    stmts: list[ast.stmt] = []
    for stmt in cls.body:
        stmts.append(stmt)
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stmts.extend(stmt.body)
    return stmts


def _windows(run: list[ast.stmt]) -> list[_Block]:
    """All windows of exactly MIN_BLOCK_STMTS consecutive statements."""
    blocks: list[_Block] = []
    for i in range(len(run) - MIN_BLOCK_STMTS + 1):
        window = run[i:i + MIN_BLOCK_STMTS]
        key = _normalize(window)
        if key:
            blocks.append(_Block(tuple(window), key))
    return blocks


def _overlaps(a: _Block, b: _Block) -> bool:
    """True if two blocks share any statement."""
    return bool(set(a.stmts) & set(b.stmts))


def _is_duplicable(stmt: ast.stmt) -> bool:
    """Statements that can participate in a duplicated block.

    Pure type declarations (`x: int` with no value) are excluded: they are
    declarations, not logic, so repeating them is not a duplication smell.
    """
    if isinstance(stmt, ast.AnnAssign):
        return stmt.value is not None
    return isinstance(stmt, (ast.Assign, ast.AugAssign, ast.Expr))


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _normalize(stmts: list[ast.stmt]) -> str:
    """Normalized source of a run: names/constants stripped, whitespace collapsed.

    Keeps the *shape* of the code (which statements, which operators, which
    attribute chains) while ignoring the specific names and values, so
    `x = a + b` and `y = c + d` normalize to the same key.
    """
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