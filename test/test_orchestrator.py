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


def test_noqa_bare_suppresses_line():
    src = """
def f(xs):
    if xs == None:  # noqa
        pass
"""
    report = OfflineOrchestrator().review_source(src)
    assert report.count == 0


def test_noqa_scoped_suppresses_only_that_rule():
    src = """
def f(xs):
    if xs == None:  # noqa: PY007
        pass
    for i in range(len(xs)):  # noqa: PY004
        print(xs[i])
"""
    report = OfflineOrchestrator().review_source(src)
    assert report.count == 0


def test_noqa_scoped_keeps_other_rules_on_line():
    src = """
def f(xs):
    if xs == None:  # noqa: PY999
        pass
"""
    report = OfflineOrchestrator().review_source(src)
    codes = {i.code for i in report.issues}
    assert "PY007" in codes


def test_noqa_does_not_suppress_other_lines():
    src = """
def f(xs):
    if xs == None:  # noqa
        pass
    for i in range(len(xs)):
        print(xs[i])
"""
    report = OfflineOrchestrator().review_source(src)
    codes = {i.code for i in report.issues}
    assert "PY004" in codes
    assert "PY007" not in codes


def test_noqa_multiple_codes():
    src = """
def f(xs):
    if xs == None:  # noqa: PY007, PY004
        pass
"""
    report = OfflineOrchestrator().review_source(src)
    assert report.count == 0