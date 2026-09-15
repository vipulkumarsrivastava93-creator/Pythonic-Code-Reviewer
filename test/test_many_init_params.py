import ast

from codereview.analyzers.detectors.many_init_params import ManyInitParams
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return ManyInitParams().detect(parse(src))


def test_few_params_no_issue():
    src = """
class Point:
    def __init__(self, x, y):
        self.x = x
        self.y = y
"""
    assert run(src) == []


def test_exactly_five_params_ok():
    src = """
class C:
    def __init__(self, a, b, c, d, e):
        pass
"""
    assert run(src) == []


def test_six_params_flagged():
    src = """
class C:
    def __init__(self, a, b, c, d, e, f):
        pass
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES002"
    assert issues[0].severity == Severity.WARNING


def test_self_not_counted():
    # 6 params + self = 7 args, but only 6 count -> flagged
    src = """
class C:
    def __init__(self, a, b, c, d, e, f):
        pass
"""
    issues = run(src)
    assert len(issues) == 1
    assert "6 parameters" in issues[0].message


def test_kwargs_counted_as_one():
    src = """
class C:
    def __init__(self, a, b, c, d, e, **kwargs):
        pass
"""
    issues = run(src)
    assert len(issues) == 1
    assert "6 parameters" in issues[0].message


def test_regular_method_not_checked():
    src = """
class C:
    def method(self, a, b, c, d, e, f, g, h):
        pass
"""
    assert run(src) == []


def test_async_init_flagged():
    src = """
class C:
    async def __init__(self, a, b, c, d, e, f):
        pass
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES002"