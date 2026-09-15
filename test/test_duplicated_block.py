import ast

from codereview.analyzers.detectors.duplicated_block import DuplicatedBlock
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return DuplicatedBlock().detect(parse(src))


def test_no_duplicates_no_issue():
    src = """
def f():
    a = 1
    b = 2
    c = 3
    return a + b + c
"""
    assert run(src) == []


def test_duplicated_block_flagged():
    src = """
def f(x, y):
    a = x + 1
    b = x + 2
    c = x + 3
    d = y + 1
    e = y + 2
    g = y + 3
    return a + b + c + d + e + g
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES003"
    assert issues[0].severity == Severity.SUGGESTION


def test_short_blocks_not_flagged():
    src = """
def f(x, y):
    a = x + 1
    b = x + 2
    c = y + 1
    d = y + 2
    return a + b + c + d
"""
    assert run(src) == []


def test_different_shapes_not_flagged():
    src = """
def f(x, y):
    a = x + 1
    b = x + 2
    c = x + 3
    d = y * 2
    e = y * 3
    g = y * 4
    return a + b + c + d + e + g
"""
    assert run(src) == []


def test_duplicates_in_different_functions_not_flagged():
    src = """
def f(x):
    a = x + 1
    b = x + 2
    c = x + 3
    return a + b + c

def g(y):
    a = y + 1
    b = y + 2
    c = y + 3
    return a + b + c
"""
    assert run(src) == []


def test_duplicates_in_same_class_methods_flagged():
    src = """
class C:
    def m1(self, x):
        a = x + 1
        b = x + 2
        c = x + 3
        return a + b + c

    def m2(self, y):
        a = y + 1
        b = y + 2
        c = y + 3
        return a + b + c
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES003"


def test_three_copies_one_issue():
    src = """
def f(x, y, z):
    a = x + 1
    b = x + 2
    c = x + 3
    d = y + 1
    e = y + 2
    g = y + 3
    h = z + 1
    i = z + 2
    j = z + 3
    return a + b + c + d + e + g + h + i + j
"""
    issues = run(src)
    assert len(issues) == 1