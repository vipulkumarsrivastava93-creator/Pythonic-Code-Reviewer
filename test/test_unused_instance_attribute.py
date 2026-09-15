import ast

from codereview.analyzers.detectors.unused_instance_attribute import UnusedInstanceAttribute
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return UnusedInstanceAttribute().detect(parse(src))


def test_used_attribute_no_issue():
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


def test_unused_attribute_flagged():
    src = """
class C:
    def __init__(self, x):
        self.x = x
        self.unused = 0

    def get(self):
        return self.x
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES007"
    assert issues[0].severity == Severity.SUGGESTION
    assert "self.unused" in issues[0].message


def test_attribute_read_in_other_method_ok():
    src = """
class C:
    def __init__(self, x):
        self.x = x

    def get(self):
        return self.x
"""
    assert run(src) == []


def test_dataclass_skipped():
    src = """
from dataclasses import dataclass

@dataclass
class Point:
    x: int
    y: int
"""
    assert run(src) == []


def test_pure_data_holder_skipped():
    src = """
class Config:
    def __init__(self, a, b):
        self.a = a
        self.b = b
"""
    assert run(src) == []


def test_write_only_cache_skipped():
    src = """
class C:
    def __init__(self):
        self._cache = {}

    def compute(self, key):
        return self._cache.get(key)
"""
    assert run(src) == []


def test_augassign_read_counts_as_use():
    src = """
class C:
    def __init__(self):
        self.count = 0

    def bump(self):
        self.count += 1
"""
    assert run(src) == []


def test_multiple_unused_flagged():
    src = """
class C:
    def __init__(self):
        self.a = 1
        self.b = 2

    def get(self):
        return 42
"""
    issues = run(src)
    assert len(issues) == 2
    assert {i.code for i in issues} == {"DES007"}


def test_used_in_repr_ok():
    src = """
class C:
    def __init__(self, x):
        self.x = x

    def __repr__(self):
        return f"C({self.x})"
"""
    assert run(src) == []