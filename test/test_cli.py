import ast
import contextlib
import io
import json

from codereview.cli import build_parser, display, main
from codereview.report import Report


def test_display_empty_report():
    buf = io.StringIO()

    with contextlib.redirect_stdout(buf):
        report = Report(path="x.py", source="")
        display(report)
    assert "good code" in buf.getvalue()


def test_main_returns_zero_on_clean(capsys):
    rc = main(["test/sample_bad.py"])
    assert rc == 0


def test_main_json_flag(capsys):
    rc = main(["--json", "test/sample_bad.py"])
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "issues" in data
    assert data["path"].endswith("sample_bad.py")


def test_main_missing_file(capsys):
    rc = main(["does_not_exist.py"])
    assert rc == 1
    assert "no such file" in capsys.readouterr().err


def test_main_invalid_syntax(capsys, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:")
    rc = main([str(bad)])
    assert rc == 1
    assert "Invalid Python" in capsys.readouterr().err


def test_build_parser_accepts_path():
    args = build_parser().parse_args(["foo.py"])
    assert args.path == "foo.py"


def test_main_recursive_directory(capsys, tmp_path):
    (tmp_path / "a.py").write_text("result = []\nfor x in [1, 2]:\n    result.append(x)\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("result = []\nfor y in [3, 4]:\n    result.append(y)\n")
    (tmp_path / "readme.md").write_text("not python")

    rc = main(["--recursive", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    assert "a.py" in out
    assert "b.py" in out


def test_main_recursive_clean_files_first_then_summary(capsys, tmp_path):
    """Clean files print before files with findings, and a summary ends output."""
    (tmp_path / "clean.py").write_text("x = 1\n")
    (tmp_path / "dirty.py").write_text("if x == None:\n    pass\n")

    rc = main(["--recursive", str(tmp_path)])

    assert rc == 0
    out = capsys.readouterr().out
    # Clean file appears before the dirty file.
    assert out.index("clean.py") < out.index("dirty.py")
    # Summary section with counts.
    assert "── Summary ──" in out
    assert "Files reviewed : 2" in out
    assert "Clean files   : 1" in out
    assert "Files with issues: 1" in out
    assert "Suggestions   : 1" in out
    assert "Warnings      : 0" in out


def test_main_recursive_requires_directory(capsys, tmp_path):
    a = tmp_path / "a.py"
    a.write_text("result = []\nfor x in [1, 2]:\n    result.append(x)\n")
    rc = main(["--recursive", str(a)])
    assert rc == 1
    assert "requires a directory" in capsys.readouterr().err


def test_main_recursive_no_python_files(capsys, tmp_path):
    (tmp_path / "readme.md").write_text("not python")
    rc = main(["--recursive", str(tmp_path)])
    assert rc == 0
    assert "No .py files found" in capsys.readouterr().err


def test_use_links_off_when_env_disabled():
    import os

    from codereview.cli import use_links

    old = os.environ.get("CODEREVIEW_LINKS")
    os.environ["CODEREVIEW_LINKS"] = "off"
    try:
        assert use_links() is False
    finally:
        if old is None:
            os.environ.pop("CODEREVIEW_LINKS", None)
        else:
            os.environ["CODEREVIEW_LINKS"] = old


def test_no_links_flag_plain_output(capsys):
    import io

    from codereview.analyzers.detectors.prefer_list_comp import PreferListComprehension
    from codereview.report import Report

    report = Report(path="x.py", source="result = []\nfor x in xs:\n    result.append(x)\n")
    report.extend(PreferListComprehension().detect(ast.parse(report.source)))
    buf = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(buf):
        display(report, links=False)
    assert "\x1b]8;;" not in buf.getvalue()


def test_editor_uri_defaults_to_vscode():
    import os

    from codereview.cli import _editor_uri

    old = os.environ.get("CODEREVIEW_EDITOR")
    os.environ.pop("CODEREVIEW_EDITOR", None)
    try:
        uri = _editor_uri("test/sample_bad.py", 3)
        assert uri.startswith("vscode://")
        assert uri.endswith(":3")
    finally:
        if old is not None:
            os.environ["CODEREVIEW_EDITOR"] = old


def test_editor_uri_file_scheme_when_override():
    import os

    from codereview.cli import _editor_uri

    old = os.environ.get("CODEREVIEW_EDITOR")
    os.environ["CODEREVIEW_EDITOR"] = "file"
    try:
        uri = _editor_uri("test/sample_bad.py", 3)
        assert uri.startswith("file:///")
        assert "file:///" == uri[:8]
    finally:
        if old is not None:
            os.environ["CODEREVIEW_EDITOR"] = old


def test_editor_uri_vscode_branch():
    import os

    from codereview.cli import _editor_uri

    old = os.environ.get("CODEREVIEW_EDITOR")
    os.environ["CODEREVIEW_EDITOR"] = "vscode"
    try:
        uri = _editor_uri("test/sample_bad.py", 3)
        assert uri.startswith("vscode://")
        assert uri.endswith(":3")
    finally:
        if old is None:
            os.environ.pop("CODEREVIEW_EDITOR", None)
        else:
            os.environ["CODEREVIEW_EDITOR"] = old


def test_display_shows_culprit_line(capsys):
    from codereview.report import Category, Issue, Severity

    report = Report(
        path="x.py",
        source="a = 1\nif x == None:\n    pass\n",
    )
    report.add(Issue(
        code="PY007", category=Category.PYTHONIC, severity=Severity.SUGGESTION,
        message="msg", line=2,
    ))
    display(report)
    out = capsys.readouterr().out
    assert "if x == None:" in out