"""Report data model: issue types, report container, deduplication."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Iterable


class Severity(enum.Enum):
    INFO = "INFO"
    SUGGESTION = "SUGGESTION"
    WARNING = "WARNING"

    def __str__(self) -> str:
        return self.value


class Category(enum.Enum):
    PYTHONIC = "pythonic"
    DESIGN = "design"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class Issue:
    code: str
    category: Category
    severity: Severity
    message: str
    line: int = 0
    column: int = 0
    end_line: int = 0

    @property
    def span(self) -> tuple[int, int]:
        return (self.line, self.end_line or self.line)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": str(self.category),
            "severity": str(self.severity),
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
        }


@dataclass
class Report:
    path: str
    source: str = ""
    issues: list[Issue] = field(default_factory=list)

    def add(self, issue: Issue) -> None:
        self.issues.append(issue)

    def extend(self, issues: Iterable[Issue]) -> None:
        for issue in issues:
            self.add(issue)

    def dedupe(self) -> None:
        seen: set[tuple] = set()
        unique: list[Issue] = []
        for issue in self.issues:
            key = (issue.code, issue.line, issue.message)
            if key in seen:
                continue
            seen.add(key)
            unique.append(issue)
        self.issues = unique

    def sort(self) -> None:
        self.issues.sort(key=lambda i: (i.line, i.category.value, i.code))

    @property
    def by_category(self) -> dict[Category, list[Issue]]:
        grouped: dict[Category, list[Issue]] = {}
        for issue in self.issues:
            grouped.setdefault(issue.category, []).append(issue)
        return grouped

    @property
    def count(self) -> int:
        return len(self.issues)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "issues": [issue.to_dict() for issue in self.issues],
        }