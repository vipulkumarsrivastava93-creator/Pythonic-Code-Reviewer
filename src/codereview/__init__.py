"""Local, dependency-free Pythonic + low-level-design code review agent."""

__all__ = [
    "RULES",
    "Category",
    "Issue",
    "OFFLINE",
    "OfflineOrchestrator",
    "Report",
    "ReviewOrchestrator",
    "Rule",
    "Severity",
    "analyze",
    "review_file",
    "review_source",
]

from codereview.analyzers import analyze
from codereview.orchestrator import OFFLINE, OfflineOrchestrator, ReviewOrchestrator
from codereview.report import Category, Issue, Report, Severity
from codereview.rules import RULES, Rule

review_file = OFFLINE.review_file
review_source = OFFLINE.review_source

__version__ = "0.1.0"