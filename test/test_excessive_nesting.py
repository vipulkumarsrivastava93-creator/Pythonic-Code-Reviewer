import ast

from codereview.analyzers.detectors.excessive_nesting import ExcessiveNesting
from codereview.report import Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


def run(src: str):
    return ExcessiveNesting().detect(parse(src))


def test_flat_code_no_issues():
    src = """
def f():
    x = 1
    return x
"""
    assert run(src) == []


def test_depth_3_ok():
    src = """
def f(items):
    for x in items:
        if x:
            pass
"""
    assert run(src) == []


def test_depth_4_flagged():
    src = """
def f(items):
    for x in items:
        for y in x:
            for z in y:
                if z:
                    pass
"""
    issues = run(src)
    assert len(issues) == 1
    assert issues[0].code == "DES005"
    assert issues[0].severity == Severity.WARNING


def test_module_level_depth_4_flagged():
    src = """
for x in xs:
    for y in xs:
        for z in xs:
            if x == y:
                print(x)
"""
    issues = run(src)
    assert len(issues) == 1


def test_class_inside_loop_not_counted():
    src = """
def outer(x):
    for i in x:
        class Inner:
            def m(self):
                pass
"""
    # def -> for -> def = 3 levels; class is a namespace, not control flow
    assert run(src) == []


def test_no_false_positive_on_methods():
    src = """
class C:
    def a(self):
        if True:
            return 1

    def b(self):
        return 2
"""
    assert run(src) == []


def test_long_elif_chain_no_false_positive():
    src = """
def f(x):
    if x == 1:
        return "one"
    elif x == 2:
        return "two"
    elif x == 3:
        return "three"
    elif x == 4:
        return "four"
    else:
        return "many"
"""
    assert run(src) == []


def test_if_else_at_depth_3_ok():
    src = """
def f(items):
    for x in items:
        if x:
            pass
        else:
            pass
"""
    assert run(src) == []


def test_elif_after_deep_inner_still_counts():
    src = """
def f(items):
    for x in items:        # for(1)
        for y in x:        # for(2)
            for z in y:    # for(3)
                if z:      # if(4) -> flagged
                    pass
                elif z.w:  # elif - same level as if (4), still flagged
                    pass
"""
    # for+for+for+if = 4 control-flow levels -> flagged (elif doesn't add)
    issues = run(src)
    assert len(issues) >= 1