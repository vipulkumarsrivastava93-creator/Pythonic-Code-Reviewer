import ast

from codereview import analyze
from codereview.analyzers.detectors import REGISTRY
from codereview.analyzers.detectors.duplicated_block import DuplicatedBlock
from codereview.analyzers.detectors.duplicated_method import DuplicatedMethod
from codereview.analyzers.detectors.excessive_nesting import ExcessiveNesting
from codereview.analyzers.detectors.large_class import LargeClass
from codereview.analyzers.detectors.many_init_params import ManyInitParams
from codereview.analyzers.detectors.nested_function import NestedFunction
from codereview.analyzers.detectors.prefer_any_all import PreferAnyAll
from codereview.analyzers.detectors.prefer_dataclass import PreferDataclass
from codereview.analyzers.detectors.prefer_defaultdict import PreferDefaultdict
from codereview.analyzers.detectors.prefer_dict_get import PreferDictGet
from codereview.analyzers.detectors.prefer_enumerate import PreferEnumerate
from codereview.analyzers.detectors.prefer_f_string import PreferFString
from codereview.analyzers.detectors.prefer_identity import PreferIdentity
from codereview.analyzers.detectors.prefer_key_sorted import PreferKeySorted
from codereview.analyzers.detectors.prefer_list_comp import PreferListComprehension
from codereview.analyzers.detectors.prefer_next_gen import PreferNextGen
from codereview.analyzers.detectors.prefer_pathlib import PreferPathlib
from codereview.analyzers.detectors.prefer_removeprefix import PreferRemovePrefix
from codereview.analyzers.detectors.prefer_str_join import PreferStrJoin
from codereview.analyzers.detectors.prefer_top_level_imports import PreferTopLevelImports
from codereview.analyzers.detectors.prefer_with_open import PreferWithOpen
from codereview.analyzers.detectors.prefer_zip import PreferZip
from codereview.analyzers.detectors.unused_instance_attribute import UnusedInstanceAttribute
from codereview.report import Category, Severity


def parse(src: str) -> ast.AST:
    return ast.parse(src)


# ---- PY001 list comprehension ----
def test_py001_detects_append_loop():
    src = """
def build(items):
    result = []
    for x in items:
        result.append(x)
    return result
"""
    issues = PreferListComprehension().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY001"


def test_py001_requires_prior_list_init():
    src = """
def build(items):
    for x in items:
        result.append(x)  # no result = [] in this scope
    return result
"""
    assert PreferListComprehension().detect(parse(src)) == []


def test_py001_skips_side_effect_expression():
    src = """
def build(items):
    result = []
    for x in items:
        result.append(process(x))
    return result
"""
    assert PreferListComprehension().detect(parse(src)) == []


def test_py001_ordered_by_line():
    src = """
def a(items):
    result = []
    for x in items:
        result.append(x)
    for y in items:
        print(y)
        result.append(y)
    return result
"""
    issues = PreferListComprehension().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].line == 4


# ---- PY004 enumerate ----
def test_py004_detects_range_len_indexing():
    src = """
def f(xs):
    for i in range(len(xs)):
        print(xs[i])
"""
    issues = PreferEnumerate().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY004"


def test_py004_ignores_non_indexed_range_len():
    src = """
def f(xs):
    for i in range(len(xs)):
        print(i)
"""
    assert PreferEnumerate().detect(parse(src)) == []


def test_py004_ignores_plain_range():
    src = """
def f(n):
    for i in range(n):
        print(i)
"""
    assert PreferEnumerate().detect(parse(src)) == []


# ---- PY007 identity ----
def test_py007_eq_none():
    src = "if x == None:\n    pass\n"
    issues = PreferIdentity().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY007"


def test_py007_neq_none():
    src = "if x != None:\n    pass\n"
    issues = PreferIdentity().detect(parse(src))
    assert len(issues) == 1


def test_py007_ignores_other_comparisons():
    src = "if x == 5:\n    pass\n"
    assert PreferIdentity().detect(parse(src)) == []


def test_py007_ignores_is():
    src = "if x is None:\n    pass\n"
    assert PreferIdentity().detect(parse(src)) == []


# ---- PY009 defaultdict ----
def test_py009_detects_init_then_append():
    src = """
def g(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            d[k].append(v)
        else:
            d[k] = [v]
    return d
"""
    issues = PreferDefaultdict().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY009"


def test_py009_ignores_plain_in():
    src = """
def h(k, d):
    if k in d:
        return d[k]
    return None
"""
    assert PreferDefaultdict().detect(parse(src)) == []


# ---- analyze() aggregating via registry ----
def test_analyze_returns_combined_issues():
    src = """
def build(items):
    result = []
    for x in items:
        result.append(x)
    for i in range(len(items)):
        print(items[i])
    if result == None:
        pass
    return result
"""
    issues = analyze(parse(src))
    codes = {i.code for i in issues}
    assert "PY001" in codes
    assert "PY004" in codes
    assert "PY007" in codes


def test_registry_contains_all_detectors():
    assert len(REGISTRY) == 23
    assert {type(d) for d in REGISTRY} == {
        PreferListComprehension,
        PreferEnumerate,
        PreferIdentity,
        PreferDefaultdict,
        PreferFString,
        PreferWithOpen,
        PreferZip,
        PreferDictGet,
        PreferAnyAll,
        PreferStrJoin,
        PreferPathlib,
        PreferDataclass,
        PreferKeySorted,
        PreferNextGen,
        PreferRemovePrefix,
        ExcessiveNesting,
        NestedFunction,
        PreferTopLevelImports,
        LargeClass,
        ManyInitParams,
        DuplicatedBlock,
        DuplicatedMethod,
        UnusedInstanceAttribute,
    }


def test_issues_have_pythonic_category():
    src = """
def f(items):
    result = []
    for x in items:
        result.append(x)
    return result
"""
    issues = analyze(parse(src))
    assert all(i.category == Category.PYTHONIC for i in issues)
    assert all(i.severity == Severity.SUGGESTION for i in issues)


# ---- PY002 f-string ----
def test_py002_detects_concat_with_variable():
    src = """
def f(name):
    return "Hello, " + name
"""
    issues = PreferFString().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY002"


def test_py002_detects_concat_variable_first():
    src = """
def f(name):
    return name + "!"
"""
    assert len(PreferFString().detect(parse(src))) == 1


def test_py002_ignores_two_literals():
    src = 'x = "a" + "b"\n'
    assert PreferFString().detect(parse(src)) == []


def test_py002_ignores_numeric_add():
    src = "x = 1 + 2\n"
    assert PreferFString().detect(parse(src)) == []


# ---- PY003 with-open ----
def test_py003_detects_bare_open():
    src = """
def f(path):
    fh = open(path)
    return fh.read()
"""
    issues = PreferWithOpen().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY003"


def test_py003_ignores_with_open():
    src = """
def f(path):
    with open(path) as fh:
        return fh.read()
"""
    assert PreferWithOpen().detect(parse(src)) == []


def test_py003_ignores_other_calls():
    src = "x = len(items)\n"
    assert PreferWithOpen().detect(parse(src)) == []


# ---- PY005 zip ----
def test_py005_detects_parallel_indexing():
    src = """
def f(as_, bs):
    for i in range(len(as_)):
        print(as_[i], bs[i])
"""
    issues = PreferZip().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY005"


def test_py005_ignores_single_sequence():
    src = """
def f(xs):
    for i in range(len(xs)):
        print(xs[i])
"""
    assert PreferZip().detect(parse(src)) == []


def test_py005_ignores_plain_range():
    src = """
def f(n):
    for i in range(n):
        print(i)
"""
    assert PreferZip().detect(parse(src)) == []


# ---- PY006 dict.get ----
def test_py006_detects_in_then_subscript():
    src = """
def f(d, k):
    if k in d:
        return d[k]
    return None
"""
    issues = PreferDictGet().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY006"


def test_py006_ignores_without_subscript():
    src = """
def f(d, k):
    if k in d:
        print("present")
"""
    assert PreferDictGet().detect(parse(src)) == []


def test_py006_ignores_with_else():
    src = """
def f(d, k):
    if k in d:
        return d[k]
    else:
        return None
"""
    assert PreferDictGet().detect(parse(src)) == []


# ---- PY010 any/all ----
def test_py010_detects_any_pattern():
    src = """
def f(xs):
    for x in xs:
        if x > 0:
            return True
    return False
"""
    issues = PreferAnyAll().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY010"
    assert "any" in issues[0].message


def test_py010_detects_all_pattern():
    src = """
def f(xs):
    for x in xs:
        if x <= 0:
            return False
    return True
"""
    issues = PreferAnyAll().detect(parse(src))
    assert len(issues) == 1
    assert "all" in issues[0].message


def test_py010_ignores_loop_without_early_return():
    src = """
def f(xs):
    for x in xs:
        if x > 0:
            print(x)
    return False
"""
    assert PreferAnyAll().detect(parse(src)) == []


# ---- PY008 str.join ----
def test_py008_detects_loop_concat():
    src = """
def f(parts):
    s = ""
    for p in parts:
        s = s + p
    return s
"""
    issues = PreferStrJoin().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY008"


def test_py008_detects_augassign():
    src = """
def f(parts):
    s = ""
    for p in parts:
        s += p
    return s
"""
    assert len(PreferStrJoin().detect(parse(src))) == 1


def test_py008_ignores_numeric_accumulation():
    src = """
def f(nums):
    total = 0
    for n in nums:
        total += n
    return total
"""
    assert PreferStrJoin().detect(parse(src)) == []


# ---- PY011 pathlib ----
def test_py011_detects_os_path_join():
    src = """
import os
def f(a, b):
    return os.path.join(a, b)
"""
    issues = PreferPathlib().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY011"


def test_py011_detects_os_path_exists():
    src = """
import os
def f(p):
    return os.path.exists(p)
"""
    assert len(PreferPathlib().detect(parse(src))) == 1


def test_py011_ignores_plain_function_call():
    src = """
def f(a, b):
    return join(a, b)
"""
    assert PreferPathlib().detect(parse(src)) == []


def test_py011_ignores_unrelated_attr():
    src = """
import os
def f(a, b):
    return os.getcwd(a, b)
"""
    assert PreferPathlib().detect(parse(src)) == []


# ---- PY012 dataclass ----
def test_py012_detects_data_only_class():
    src = """
class Point:
    x = 0
    y = 0
"""
    issues = PreferDataclass().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY012"


def test_py012_detects_annotated_fields():
    src = """
class Point:
    x: int = 0
    y: int = 0
"""
    assert len(PreferDataclass().detect(parse(src))) == 1


def test_py012_ignores_class_with_methods():
    src = """
class Counter:
    count = 0
    def inc(self):
        self.count += 1
"""
    assert PreferDataclass().detect(parse(src)) == []


# ---- PY013 key= ----
def test_py013_detects_manual_comparator():
    src = """
def f(xs):
    return sorted(xs, lambda a, b: a.x < b.x)
"""
    issues = PreferKeySorted().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY013"


def test_py013_ignores_single_arg_key():
    src = """
def f(xs):
    return sorted(xs, key=lambda x: x.x)
"""
    assert PreferKeySorted().detect(parse(src)) == []


# ---- PY014 next() ----
def test_py014_detects_first_item_loop():
    src = """
def f(xs):
    for x in xs:
        if x > 0:
            return x
    return None
"""
    issues = PreferNextGen().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY014"


def test_py014_ignores_loop_without_default_return():
    src = """
def f(xs):
    for x in xs:
        if x > 0:
            return x
    print("done")
"""
    assert PreferNextGen().detect(parse(src)) == []


# ---- PY015 removeprefix ----
def test_py015_detects_prefix_slice():
    src = """
def f(s, prefix):
    return s[len(prefix):]
"""
    issues = PreferRemovePrefix().detect(parse(src))
    assert len(issues) == 1
    assert issues[0].code == "PY015"


def test_py015_detects_suffix_slice():
    src = """
def f(s, suffix):
    return s[:-len(suffix)]
"""
    assert len(PreferRemovePrefix().detect(parse(src))) == 1


def test_py015_ignores_general_indexing():
    src = """
def f(s):
    return s[1:]
"""
    assert PreferRemovePrefix().detect(parse(src)) == []


# ---- regression: scanners must not crash on non-AST list fields ----
def test_scanners_ignore_global_nonlocal_names():
    """`global`/`nonlocal` have list-of-str fields; scanners must skip them."""
    src = """
def f():
    global x
    for i in range(3):
        if i:
            return i
    return None
"""
    # Must not raise AttributeError on the str elements of Global.names.
    assert PreferAnyAll().detect(parse(src)) == []
    assert len(PreferNextGen().detect(parse(src))) == 1