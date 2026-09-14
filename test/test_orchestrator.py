import ast

import pytest

from codereview.orchestrator import OFFLINE, OfflineOrchestrator, ReviewOrchestrator


def test_offline_review_file_finds_known_issues():
    report = OfflineOrchestrator().review_file("test/sample_bad.py")
    codes = {i.code for i in report.issues}
    assert {"PY001", "PY004", "PY007", "PY009"} <= codes


def test_review_source_dedupes_and_sorts():
    src = """
def f(xs):
    if xs == None:
        pass
    for i in range(len(xs)):
        print(xs[i])
"""
    report = OfflineOrchestrator().review_source(src)
    issues = report.issues
    lines = [i.line for i in issues]
    assert lines == sorted(lines)
    # no duplicate issue on the same (code, line, message)
    keys = {(i.code, i.line, i.message) for i in issues}
    assert len(keys) == len(issues)


def test_review_source_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        OfflineOrchestrator().review_source("def broken(:")


def test_base_orchestrator_is_abstract():
    with pytest.raises(TypeError):
        ReviewOrchestrator()


def test_offline_singleton_usable():
    report = OFFLINE.review_source("x = 1\n")
    assert report.count == 0