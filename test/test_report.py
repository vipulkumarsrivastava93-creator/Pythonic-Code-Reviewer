import pytest

from codereview.report import Category, Issue, Report, Severity


def make_issue(code="PY001", line=3, message="m", *, category=None, severity=None):
    return Issue(
        code=code,
        category=category or Category.PYTHONIC,
        severity=severity or Severity.SUGGESTION,
        message=message,
        line=line,
    )


def test_issue_span_defaults_to_line():
    issue = make_issue(line=5)
    assert issue.span == (5, 5)


def test_issue_frozen():
    issue = make_issue()
    with pytest.raises(Exception):
        issue.code = "PY999"


def test_report_add_and_extend():
    r = Report(path="x.py", source="")
    r.add(make_issue(line=1))
    r.extend([make_issue(line=2), make_issue(line=3)])
    assert r.count == 3


def test_report_dedupe_removes_exact_duplicates():
    r = Report(path="x.py")
    r.extend([make_issue(line=1), make_issue(line=1)])
    r.dedupe()
    assert r.count == 1


def test_report_sort_by_line_then_category():
    r = Report(path="x.py")
    r.add(make_issue(code="DES001", category=Category.DESIGN, line=5))
    r.add(make_issue(code="PY001", line=2))
    r.add(make_issue(code="PY002", line=2))
    r.sort()
    assert [i.code for i in r.issues] == ["PY001", "PY002", "DES001"]


def test_report_by_category():
    r = Report(path="x.py")
    r.add(make_issue(code="PY001", line=1))
    r.add(make_issue(code="DES001", category=Category.DESIGN, line=2))
    grouped = r.by_category
    assert set(grouped) == {Category.PYTHONIC, Category.DESIGN}
    assert len(grouped[Category.PYTHONIC]) == 1


def test_report_count():
    r = Report(path="x.py")
    assert r.count == 0
    r.add(make_issue())
    assert r.count == 1