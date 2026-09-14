import ast

from codereview.analyzers.detectors.prefer_top_level_imports import PreferTopLevelImports


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return PreferTopLevelImports().detect(parse(src))


def test_import_inside_function_flagged():
    src = """
def f():
    import os
    return os.path.join("a", "b")
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "PY016"
    assert "os" in issues[0].message


def test_method_import_flagged():
    src = """
class C:
    def m(self):
        from math import sqrt
        return sqrt(4)
"""
    issues = run(src)
    assert len(issues) == 1


def test_top_level_import_not_flagged():
    src = "import os\n\ndef f():\n    return os.name\n"
    assert run(src) == []


def test_import_under_try_skipped():
    src = """
def f():
    try:
        import numpy as np
    except ImportError:
        np = None
    return np
"""
    assert run(src) == []


def test_import_under_type_checking_skipped():
    src = """
def f():
    if TYPE_CHECKING:
        from typing import List
    return []
"""
    assert run(src) == []


def test_class_body_import_not_flagged():
    src = """
class C:
    import os
    pass
"""
    # module-like class body; not inside a function
    assert run(src) == []