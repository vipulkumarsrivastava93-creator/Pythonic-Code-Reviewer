import ast

from codereview.analyzers.detectors.duplicated_method import DuplicatedMethod
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return DuplicatedMethod().detect(parse(src))


def test_no_duplicates_no_issue():
    src = """
class A:
    def m1(self, x):
        a = x + 1
        b = x + 2
        c = x + 3
        return a + b + c

class B:
    def m2(self, y):
        a = y * 2
        b = y * 3
        c = y * 4
        return a + b + c
"""
    assert run(src) == []


def test_duplicated_method_flagged():
    src = """
class A:
    def m1(self, x):
        a = x + 1
        b = x + 2
        c = x + 3
        return a + b + c

class B:
    def m2(self, y):
        a = y + 1
        b = y + 2
        c = y + 3
        return a + b + c
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES004"
    assert issues[0].severity == Severity.SUGGESTION


def test_short_methods_not_flagged():
    src = """
class A:
    def m1(self, x):
        return x + 1

class B:
    def m2(self, y):
        return y + 1
"""
    assert run(src) == []


def test_init_duplicates_ignored():
    src = """
class A:
    def __init__(self, x):
        self.x = x
        self.y = 0
        self.z = 0

class B:
    def __init__(self, y):
        self.x = y
        self.y = 0
        self.z = 0
"""
    assert run(src) == []


def test_duplicates_in_same_class_flagged():
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
    assert issues[0].code == "DES004"


def test_different_names_same_body_flagged():
    src = """
class A:
    def compute(self, x):
        a = x + 1
        b = x + 2
        c = x + 3
        return a + b + c

class B:
    def calculate(self, y):
        a = y + 1
        b = y + 2
        c = y + 3
        return a + b + c
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES004"