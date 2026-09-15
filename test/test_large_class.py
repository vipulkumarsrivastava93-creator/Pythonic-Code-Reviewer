import ast

from codereview.analyzers.detectors.large_class import LargeClass
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return LargeClass().detect(parse(src))


def test_small_class_no_issue():
    src = """
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def move(self, dx, dy):
        self.x += dx
        self.y += dy
"""
    assert run(src) == []


def test_large_class_flagged():
    # 101+ lines of real code in the body
    lines = ["class Big:"]
    for i in range(105):
        lines.append(f"    attr{i} = {i}")
    src = "\n".join(lines)
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES001"
    assert issues[0].severity == Severity.INFO


def test_docstring_not_counted():
    # 100 real lines + a long docstring should NOT be flagged
    lines = ["class Big:", '    """' + "x" * 200 + '"""']
    for i in range(100):
        lines.append(f"    attr{i} = {i}")
    src = "\n".join(lines)
    assert run(src) == []


def test_nested_class_also_checked():
    lines = ["class Outer:", "    class Inner:"]
    for i in range(105):
        lines.append(f"        attr{i} = {i}")
    src = "\n".join(lines)
    issues = run(src)
    codes = {i.code for i in issues}
    assert "DES001" in codes


def test_exactly_at_limit_not_flagged():
    lines = ["class JustRight:"]
    for i in range(100):
        lines.append(f"    attr{i} = {i}")
    src = "\n".join(lines)
    assert run(src) == []