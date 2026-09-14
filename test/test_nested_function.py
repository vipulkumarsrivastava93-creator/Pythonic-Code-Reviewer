import ast

from codereview.analyzers.detectors.nested_function import NestedFunction


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return NestedFunction().detect(parse(src))


def test_no_nested_function():
    src = """
def top():
    return 1
"""
    assert run(src) == []


def test_plain_nested_function_flagged():
    src = """
def outer():
    def inner():
        return 1
    return inner()
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES006"
    assert "inner" in issues[0].message


def test_decorated_nested_function_skipped():
    src = """
def outer():
    @staticmethod
    def inner():
        return 1
    return inner
"""
    assert run(src) == []


def test_passed_as_callback_skipped():
    src = """
def outer(data):
    def key(x):
        return x.id
    return sorted(data, key=key)
"""
    issues = run(src)
    assert len(issues) == 0


def test_nested_under_control_flow_still_flagged():
    src = """
def outer(data):
    if data:
        def helper():
            return 1
        return helper()
    return None
"""
    issues = run(src)
    assert len(issues) == 1


def test_factory_returned_closure_flagged():
    src = """
def make_counter():
    count = 0
    def counter():
        return count
    return counter
"""
    # Returned closures are not a carve-out (only decorated/passed-as-callback).
    issues = run(src)
    assert len(issues) == 1