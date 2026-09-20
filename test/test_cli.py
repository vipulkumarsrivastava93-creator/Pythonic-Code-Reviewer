import ast
import contextlib
import io
import json
from pathlib import Path

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


# ---- --setup flag ----

def test_main_setup_no_path_needed(monkeypatch, capsys):
    """`codereview --setup` installs the model without requiring a path."""
    calls = []
    monkeypatch.setattr("codereview.cli.ensure_model",
                        lambda **kw: calls.append(kw))
    monkeypatch.setattr("codereview.cli.ensure_embed_model",
                        lambda **kw: calls.append(kw))
    rc = main(["--setup"])
    assert rc == 0
    assert calls[0] == {"yes": False, "force_menu": True,
                         "announce": calls[0]["announce"]}
    assert calls[1] == {"yes": False, "announce": calls[1]["announce"]}
    assert "Setup complete" in capsys.readouterr().out


def test_main_setup_yes_flag(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("codereview.cli.ensure_model",
                        lambda **kw: calls.append(kw))
    monkeypatch.setattr("codereview.cli.ensure_embed_model",
                        lambda **kw: calls.append(kw))
    rc = main(["--setup", "--yes"])
    assert rc == 0
    assert calls[0] == {"yes": True, "force_menu": True,
                         "announce": calls[0]["announce"]}
    assert calls[1] == {"yes": True, "announce": calls[1]["announce"]}


def test_main_setup_declined_returns_1(monkeypatch, capsys):
    from codereview.llm import ModelInstallError
    def decline(**kw):
        raise ModelInstallError("declined")
    monkeypatch.setattr("codereview.cli.ensure_model", decline)
    monkeypatch.setattr("codereview.cli.ensure_embed_model",
                        lambda **kw: None)
    rc = main(["--setup"])
    assert rc == 1
    assert "Setup incomplete" in capsys.readouterr().err


def test_main_no_path_prints_error(capsys):
    """No path and no --setup flag -> usage error, exit 2."""
    rc = main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "path" in err or "setup" in err


def test_main_llm_recursive_with_path(monkeypatch, capsys, tmp_path):
    """--llm -r <dir> still works: path is not swallowed as a subcommand."""
    (tmp_path / "a.py").write_text("if x == None:\n    pass\n")
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    rc = main(["--llm", "--recursive", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.py" in out


def test_main_llm_parallel_workers_flag(monkeypatch, capsys, tmp_path):
    """--workers is accepted and parallel review works with mocked LLM."""
    (tmp_path / "a.py").write_text("if x == None:\n    pass\n")
    (tmp_path / "b.py").write_text("result = []\nfor x in [1]:\n    result.append(x)\n")
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    monkeypatch.setattr("codereview.cli.review_with_llm",
                        lambda *a, **k: [])
    rc = main(["--llm", "--recursive", "--workers", "2", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.py" in out
    assert "b.py" in out


def test_main_llm_parallel_single_file(monkeypatch, capsys, tmp_path):
    """Single file with --llm still works (sequential path)."""
    (tmp_path / "a.py").write_text("if x == None:\n    pass\n")
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    monkeypatch.setattr("codereview.cli.review_with_llm",
                        lambda *a, **k: [])
    rc = main(["--llm", str(tmp_path / "a.py")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.py" in out


def test_main_rag_embed_implies_llm(monkeypatch, capsys, tmp_path):
    """--rag-embed alone implies --llm (RAG is meaningless without the LLM)."""
    # File must be above MIN_LLM_LINES so the LLM path actually runs.
    (tmp_path / "a.py").write_text(
        "def f(xs):\n"
        "    result = []\n"
        "    for x in xs:\n"
        "        result.append(x)\n"
        "    return result\n"
        "\n"
        "def g():\n"
        "    return f([1, 2, 3])\n"
        "\n"
        "def h():\n"
        "    return g()\n"
    )
    called = []
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    monkeypatch.setattr("codereview.cli.review_with_llm",
                        lambda *a, **k: called.append(a) or [])
    rc = main(["--rag-embed", str(tmp_path / "a.py")])
    assert rc == 0
    assert called != []  # LLM was invoked even without --llm


def test_main_llm_skips_tiny_files(monkeypatch, capsys, tmp_path):
    """Files under MIN_LLM_LINES don't call the LLM (no hallucination risk)."""
    from codereview.cli import MIN_LLM_LINES
    tiny = tmp_path / "tiny.py"
    tiny.write_text('"""Docstring."""\nimport sys\n\nfrom x import main\n')
    assert len(tiny.read_text().splitlines()) < MIN_LLM_LINES

    called = []
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    monkeypatch.setattr("codereview.cli.review_with_llm",
                        lambda *a, **k: called.append(a))
    rc = main(["--llm", str(tiny)])
    assert rc == 0
    assert called == []  # LLM never invoked for tiny file


def test_main_consistency_skipped_when_siblings_match(monkeypatch, capsys, tmp_path):
    """--rag-embed skips the consistency LLM call when siblings match."""
    from codereview.cli import _review_consistency
    (tmp_path / "base.py").write_text("class Detector:\n    pass\n")
    (tmp_path / "a.py").write_text(
        "from base import Detector\n"
        "\n"
        "class A(Detector):\n"
        "    def run(self):\n"
        "        return 1\n"
        "\n"
        "def helper():\n"
        "    return A().run()\n"
        "\n"
        "def main():\n"
        "    return helper()\n"
    )
    (tmp_path / "b.py").write_text(
        "from base import Detector\n"
        "\n"
        "class B(Detector):\n"
        "    def run(self):\n"
        "        return 2\n"
        "\n"
        "def helper():\n"
        "    return B().run()\n"
        "\n"
        "def main():\n"
        "    return helper()\n"
    )
    consistency_calls = []
    monkeypatch.setattr("codereview.cli.ensure_model", lambda **kw: None)
    monkeypatch.setattr("codereview.cli.review_with_llm",
                        lambda *a, **k: [])
    monkeypatch.setattr("codereview.cli._review_consistency",
                        lambda *a, **k: consistency_calls.append(a) or [])
    rc = main(["--rag-embed", str(tmp_path / "a.py")])
    assert rc == 0
    assert consistency_calls == []  # siblings match -> consistency skipped


# ---- export prompt ----

def test_maybe_export_writes_file_when_yes(monkeypatch, tmp_path, capsys):
    """User says yes -> findings written to codereview_findings.txt."""
    from codereview.cli import _maybe_export
    from codereview.report import Report, Issue, Category, Severity
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    monkeypatch.chdir(tmp_path)
    report = Report(path="x.py")
    report.add(Issue(code="PY001", category=Category.PYTHONIC,
                     severity=Severity.SUGGESTION, message="Use a comp.", line=3))
    _maybe_export([(Path("x.py"), report)])
    out = (tmp_path / "codereview_findings.txt").read_text(encoding="utf-8")
    assert "PY001" in out
    assert "x.py" in out


def test_maybe_export_noop_when_no(monkeypatch, tmp_path, capsys):
    """User says no -> no file written."""
    from codereview.cli import _maybe_export
    from codereview.report import Report, Issue, Category, Severity
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    monkeypatch.chdir(tmp_path)
    report = Report(path="x.py")
    report.add(Issue(code="PY001", category=Category.PYTHONIC,
                     severity=Severity.SUGGESTION, message="Use a comp.", line=3))
    _maybe_export([(Path("x.py"), report)])
    assert not (tmp_path / "codereview_findings.txt").exists()


def test_maybe_export_noop_when_clean(monkeypatch, tmp_path, capsys):
    """No findings -> no prompt, no file."""
    from codereview.cli import _maybe_export
    from codereview.report import Report
    monkeypatch.setattr("builtins.input", lambda *a: "y")
    monkeypatch.chdir(tmp_path)
    _maybe_export([(Path("x.py"), Report(path="x.py"))])
    assert not (tmp_path / "codereview_findings.txt").exists()