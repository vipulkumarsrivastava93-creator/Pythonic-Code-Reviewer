import ast
from pathlib import Path

from codereview import analyze


def test_sample_bad_triggers_all_detectors():
    source = Path(__file__).with_name("sample_bad.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    issues = analyze(tree)
    codes = {i.code for i in issues}
    assert {"PY001", "PY004", "PY007", "PY009"} <= codes