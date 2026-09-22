"""Tests for the LLM reviewer adapter (no network required)."""

from __future__ import annotations

import json

import pytest

from codereview.llm.reviewer import (
    LLMError,
    LLMReviewer,
    _build_prompt,
    _extract_content,
    _parse_severity,
    _parse_suggestions,
    _summarize,
)
from codereview.rag import CodebaseIndex
from codereview.report import Category, Severity


# ---- _parse_suggestions ----

def test_parse_suggestions_basic():
    content = json.dumps({
        "suggestions": [
            {"line": 3, "message": "Use a list comprehension.", "severity": "SUGGESTION"},
            {"line": 10, "message": "Consider extracting a helper.", "severity": "WARNING"},
        ]
    })
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 2
    assert issues[0].code == "LLM001"
    assert issues[0].category == Category.DESIGN
    assert issues[0].severity == Severity.SUGGESTION
    assert issues[0].line == 3
    assert issues[1].severity == Severity.WARNING


def test_parse_suggestions_empty():
    assert _parse_suggestions('{"suggestions": []}', "x.py") == []


def test_parse_suggestions_markdown_fence():
    content = '```json\n{"suggestions": [{"line": 1, "message": "Fix it.", "severity": "INFO"}]}\n```'
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 1
    assert issues[0].severity == Severity.INFO


def test_parse_suggestions_skips_bad_items():
    content = json.dumps({
        "suggestions": [
            {"line": "not-an-int", "message": "bad line"},
            {"line": 5, "message": ""},          # empty message
            {"line": 7, "message": "Good one.", "severity": "SUGGESTION"},
            "not-a-dict",
        ]
    })
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 1
    assert issues[0].line == 7


def test_parse_suggestions_invalid_json_returns_empty():
    """Garbage that can't be salvaged returns no issues (no crash)."""
    assert _parse_suggestions("not json at all", "x.py") == []


def test_parse_suggestions_not_object_returns_empty():
    assert _parse_suggestions("[1, 2, 3]", "x.py") == []


def test_parse_suggestions_trailing_comma():
    """Trailing commas before } are tolerated (common small-model mistake)."""
    content = '{"suggestions": [{"line": 1, "message": "Fix it.", "severity": "INFO"},]}'
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 1
    assert issues[0].line == 1


def test_parse_suggestions_truncated_output_salvaged():
    """Truncated JSON (cut off at max_tokens) still yields what's parseable."""
    content = ('```json\n{"suggestions": [\n'
               '  {"line": 35, "message": "First issue.", "severity": "WARNING"},\n'
               '  {"line": 40, "message": "Second issue.", "severity": "SUGGESTION"},\n'
               '  {"line": 45, "message": "Truncated...')
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 2
    assert issues[0].line == 35
    assert issues[1].line == 40


def test_parse_suggestions_suggestions_not_list_returns_empty():
    """'suggestions' not a list -> nothing usable, no crash."""
    assert _parse_suggestions('{"suggestions": "nope"}', "x.py") == []


def test_parse_suggestions_caps_at_max():
    many = {"suggestions": [
        {"line": i, "message": f"msg {i}", "severity": "INFO"} for i in range(1, 20)
    ]}
    issues = _parse_suggestions(json.dumps(many), "x.py")
    assert len(issues) == 5  # _MAX_SUGGESTIONS


def test_parse_suggestions_filters_hallucinated_lines():
    """Issues pointing at lines that don't exist in the source are dropped."""
    src = "x = 1\ny = 2\n"
    content = json.dumps({"suggestions": [
        {"line": 1, "message": "Real line.", "severity": "INFO"},
        {"line": 99, "message": "Hallucinated line.", "severity": "INFO"},
    ]})
    issues = _parse_suggestions(content, "x.py", src)
    assert len(issues) == 1
    assert issues[0].line == 1


def test_parse_suggestions_filters_stripped_import_lines():
    """Issues on stripped import lines are dropped (model can't see them)."""
    src = "import os\nx = 1\n"
    content = json.dumps({"suggestions": [
        {"line": 1, "message": "Comment on import.", "severity": "INFO"},
        {"line": 2, "message": "Real finding.", "severity": "INFO"},
    ]})
    issues = _parse_suggestions(content, "x.py", src, stripped_lines={1})
    assert len(issues) == 1
    assert issues[0].line == 2


def test_stripped_lines_finds_imports():
    from codereview.llm.reviewer import _stripped_lines
    src = "import os\nfrom pathlib import Path\n\nx = 1\n"
    assert _stripped_lines(src) == {1, 2}


def test_stripped_lines_finds_docstrings():
    """Docstrings are prose, not code — blanked so the model can't read them as code."""
    from codereview.llm.reviewer import _stripped_lines
    src = '"""Module docstring."""\n\ndef f() -> None:\n    """Function docstring."""\n    x = 1\n'
    assert _stripped_lines(src) == {1, 4}


def test_stripped_lines_multiline_docstring():
    from codereview.llm.reviewer import _stripped_lines
    src = '"""Line one.\nLine two.\nLine three."""\nx = 1\n'
    assert _stripped_lines(src) == {1, 2, 3}


def test_parse_suggestions_no_source_skips_filter():
    """Without source, no filtering happens (backwards compatible)."""
    content = json.dumps({"suggestions": [
        {"line": 99, "message": "Any line.", "severity": "INFO"},
    ]})
    issues = _parse_suggestions(content, "x.py")
    assert len(issues) == 1


def test_parse_suggestions_unparseable_source_no_filter():
    """Unparseable source -> no filtering (can't know real lines)."""
    content = json.dumps({"suggestions": [
        {"line": 5, "message": "msg", "severity": "INFO"},
    ]})
    issues = _parse_suggestions(content, "x.py", "def broken(:")
    assert len(issues) == 1


# ---- _parse_severity ----

def test_parse_severity_valid():
    assert _parse_severity("WARNING") == Severity.WARNING
    assert _parse_severity("info") == Severity.INFO


def test_parse_severity_invalid_defaults_to_suggestion():
    assert _parse_severity("CRITICAL") == Severity.SUGGESTION
    assert _parse_severity(None) == Severity.SUGGESTION


# ---- _extract_content ----

def test_extract_content_ok():
    payload = {"choices": [{"message": {"content": "hello"}}]}
    assert _extract_content(payload) == "hello"


def test_extract_content_missing_raises():
    with pytest.raises(LLMError):
        _extract_content({})


# ---- _summarize / _build_prompt ----

def test_summarize_lists_definitions():
    src = "import os\n\ndef f():\n    pass\n\nclass C:\n    pass\n"
    summary = _summarize(src)
    assert "def f" in summary
    assert "class C" in summary
    assert "import" not in summary  # imports excluded to avoid LLM noise


def test_summarize_unparseable():
    assert _summarize("def broken(:") == "(unparseable)"


def test_build_prompt_contains_source_and_summary():
    src = "x = 1\n"
    prompt = _build_prompt(src, "test.py")
    assert "test.py" in prompt
    assert "x = 1" in prompt
    assert "suggestions" in prompt


def test_build_prompt_passes_related_context():
    """RAG context is injected into the prompt when provided."""
    src = "x = 1\n"
    prompt = _build_prompt(src, "test.py", related="  base.py: class VisitorDetector")
    assert "Related code context" in prompt
    assert "VisitorDetector" in prompt


def test_build_prompt_omits_related_when_empty():
    """No RAG context -> no related block (backwards compatible)."""
    src = "x = 1\n"
    prompt = _build_prompt(src, "test.py")
    assert "Related code context (same codebase" not in prompt


def test_build_prompt_strips_imports():
    """Import statements are removed from the source sent to the model."""
    src = "import os\nfrom pathlib import Path\n\nx = 1\n"
    prompt = _build_prompt(src, "test.py")
    assert "import os" not in prompt
    assert "from pathlib" not in prompt
    assert "x = 1" in prompt


def test_build_prompt_strips_docstrings():
    """Docstrings are removed so the model can't read prose as code."""
    src = '"""PY007: == None / != None -> is None / is not None."""\nx = 1\n'
    prompt = _build_prompt(src, "test.py")
    assert "== None" not in prompt
    assert "x = 1" in prompt


def test_strip_imports_preserves_line_numbers():
    from codereview.llm.reviewer import _strip_imports
    src = "import os\nfrom pathlib import Path\n\nx = 1\n"
    stripped = _strip_imports(src)
    assert stripped.splitlines()[0] == ""  # line 1 blanked
    assert stripped.splitlines()[1] == ""  # line 2 blanked
    assert stripped.splitlines()[3] == "x = 1"  # line 4 intact


def test_strip_imports_no_imports_unchanged():
    from codereview.llm.reviewer import _strip_imports
    src = "x = 1\ny = 2\n"
    assert _strip_imports(src) == src


def test_strip_imports_blanks_docstrings():
    """Docstrings are blanked out, preserving line numbers."""
    from codereview.llm.reviewer import _strip_imports
    src = '"""Module docstring."""\n\ndef f() -> None:\n    """Inner docstring."""\n    x = 1\n'
    stripped = _strip_imports(src)
    assert stripped.splitlines()[0] == ""       # module docstring blanked
    assert stripped.splitlines()[3] == ""       # inner docstring blanked
    assert stripped.splitlines()[4] == "    x = 1"  # code intact


def test_strip_imports_blanks_multiline_docstring():
    from codereview.llm.reviewer import _strip_imports
    src = '"""Line one.\nLine two."""\nx = 1\n'
    stripped = _strip_imports(src)
    assert stripped.splitlines()[0] == ""
    assert stripped.splitlines()[1] == ""
    assert stripped.splitlines()[2] == "x = 1"


def test_strip_imports_unparseable_unchanged():
    from codereview.llm.reviewer import _strip_imports
    src = "def broken(:"
    assert _strip_imports(src) == src


def test_build_prompt_includes_static_findings():
    from codereview.report import Issue
    src = "x = 1\n"
    static = [Issue(code="PY001", category=Category.PYTHONIC,
                    severity=Severity.SUGGESTION, message="Use a comp.", line=1)]
    prompt = _build_prompt(src, "test.py", static)
    assert "PY001" in prompt
    assert "do NOT repeat" in prompt


def test_build_prompt_no_static_findings_omits_block():
    src = "x = 1\n"
    prompt = _build_prompt(src, "test.py")
    assert "do NOT repeat" not in prompt


# ---- prompts module ----

def test_prompts_system_prompt_exists():
    from codereview.llm.prompts import SYSTEM_PROMPT
    assert "senior Python code reviewer" in SYSTEM_PROMPT


def test_prompts_rules_forbid_imports_and_type_hints():
    from codereview.llm.prompts import COMMON_RULES
    joined = " ".join(COMMON_RULES)
    assert "imports" in joined
    assert "type hints" in joined


def test_prompts_has_both_focuses():
    from codereview.llm.prompts import FOCUS_PROMPTS
    assert "design" in FOCUS_PROMPTS
    assert "logic" in FOCUS_PROMPTS


def test_prompts_design_focus_mentions_classes():
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n",
                               focus="design")
    assert "class designs" in prompt
    assert "responsibility" in prompt


def test_prompts_logic_focus_mentions_correctness():
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n",
                               focus="logic")
    assert "correctness" in prompt
    assert "edge cases" in prompt


def test_prompts_related_block_included_when_given():
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n",
                               related="  base.py: class VisitorDetector")
    assert "Related code context" in prompt
    assert "VisitorDetector" in prompt


def test_prompts_related_block_omitted_when_empty():
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n")
    assert "Related code context (same codebase" not in prompt


def test_prompts_related_rules_injected_when_related():
    """Sibling-comparison rules appear only when related context is given."""
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n",
                               related="  base.py: class VisitorDetector")
    assert "SIBLING code" in prompt
    assert "deviations from the siblings" in prompt


def test_prompts_related_rules_absent_without_related():
    """No related context -> no sibling rules (backwards compatible)."""
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n")
    assert "SIBLING code" not in prompt
    assert "deviations from the siblings" not in prompt


def test_prompts_invalid_focus_raises():
    import pytest
    from codereview.llm.prompts import build_user_prompt
    with pytest.raises(ValueError):
        build_user_prompt(path="x.py", summary="", source="x = 1\n",
                          focus="bogus")


def test_prompts_build_user_prompt():
    from codereview.llm.prompts import build_user_prompt
    prompt = build_user_prompt(path="x.py", summary="def f (line 1)",
                               source="x = 1\n")
    assert "x.py" in prompt
    assert "def f (line 1)" in prompt
    assert "x = 1" in prompt
    assert "suggestions" in prompt


def test_prompts_build_user_prompt_with_static():
    from codereview.llm.prompts import build_user_prompt
    from codereview.report import Issue
    static = [Issue(code="PY001", category=Category.PYTHONIC,
                    severity=Severity.SUGGESTION, message="Use a comp.", line=1)]
    prompt = build_user_prompt(path="x.py", summary="", source="x = 1\n",
                               static_issues=static)
    assert "PY001" in prompt
    assert "do NOT repeat" in prompt


# ---- LLMReviewer config ----

def test_reviewer_defaults_to_local_ollama(monkeypatch):
    monkeypatch.delenv("CODEREVIEW_LLM_URL", raising=False)
    monkeypatch.delenv("CODEREVIEW_LLM_API_KEY", raising=False)
    r = LLMReviewer()
    assert "localhost" in r.url
    assert r.is_local


def test_reviewer_remote_when_api_key_set(monkeypatch):
    monkeypatch.delenv("CODEREVIEW_LLM_URL", raising=False)
    monkeypatch.setenv("CODEREVIEW_LLM_API_KEY", "sk-test")
    r = LLMReviewer()
    assert r.url == "https://api.openai.com/v1/chat/completions"
    assert not r.is_local


def test_reviewer_explicit_url_wins(monkeypatch):
    monkeypatch.setenv("CODEREVIEW_LLM_URL", "http://example.com/v1/chat/completions")
    monkeypatch.setenv("CODEREVIEW_LLM_API_KEY", "sk-test")
    r = LLMReviewer()
    assert r.url == "http://example.com/v1/chat/completions"


def test_reviewer_model_env(monkeypatch):
    monkeypatch.setenv("CODEREVIEW_LLM_MODEL", "my-model")
    r = LLMReviewer()
    assert r.model == "my-model"


def test_reviewer_auto_picks_best_installed_model(monkeypatch):
    """No env override -> uses the largest installed model."""
    monkeypatch.delenv("CODEREVIEW_LLM_MODEL", raising=False)
    monkeypatch.setattr("codereview.llm.reviewer.pick_best_model",
                        lambda: "deepseek-r1:7b")
    r = LLMReviewer()
    assert r.model == "deepseek-r1:7b"


def test_reviewer_falls_back_to_default_when_none_installed(monkeypatch):
    """No env override, nothing installed -> DEFAULT_MODEL."""
    monkeypatch.delenv("CODEREVIEW_LLM_MODEL", raising=False)
    monkeypatch.setattr("codereview.llm.reviewer.pick_best_model", lambda: None)
    r = LLMReviewer()
    assert r.model == "deepseek-r1:7b"


# ---- pick_best_model / installed_models / cleanup ----

def test_pick_best_model_returns_installed(monkeypatch):
    from codereview.llm.installer import pick_best_model
    monkeypatch.setattr("codereview.llm.installer.installed_models",
                        lambda: {"deepseek-r1:7b"})
    assert pick_best_model() == "deepseek-r1:7b"


def test_pick_best_model_none_installed(monkeypatch):
    from codereview.llm.installer import pick_best_model
    monkeypatch.setattr("codereview.llm.installer.installed_models", lambda: set())
    assert pick_best_model() is None


def test_installed_models_parses_ollama_list(monkeypatch):
    from codereview.llm.installer import installed_models
    class FakeOut:
        stdout = "NAME\tID\tSIZE\tMODIFIED\ndeepseek-r1:7b\tabc\t4.7 GB\ttoday\n"
    monkeypatch.setattr("codereview.llm.installer._ollama_binary", lambda: "ollama")
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: FakeOut())
    assert installed_models() == {"deepseek-r1:7b"}


def test_cleanup_removes_smaller_models(monkeypatch):
    """Only deepseek-r1:7b is in MODEL_CHOICES; nothing ranks below it."""
    from codereview.llm.installer import _cleanup_smaller_models
    calls = []
    monkeypatch.setattr("codereview.llm.installer._ollama_binary", lambda: "ollama")
    monkeypatch.setattr("codereview.llm.installer.installed_models",
                        lambda: {"deepseek-r1:7b", "qwen2.5-coder:7b"})
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(a[0]))
    _cleanup_smaller_models("deepseek-r1:7b", lambda m: None)
    assert calls == []  # qwen is not in MODEL_CHOICES; never touched


def test_cleanup_keeps_unrelated_models(monkeypatch):
    from codereview.llm.installer import _cleanup_smaller_models
    calls = []
    monkeypatch.setattr("codereview.llm.installer._ollama_binary", lambda: "ollama")
    monkeypatch.setattr("codereview.llm.installer.installed_models",
                        lambda: {"llama3:8b", "deepseek-r1:7b"})
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(a[0]))
    _cleanup_smaller_models("deepseek-r1:7b", lambda m: None)
    assert calls == []  # llama3:8b is not in MODEL_CHOICES; never touched


# ---- review() with a stubbed _post ----

def test_review_parses_model_output(monkeypatch):
    r = LLMReviewer()
    payload = {"choices": [{"message": {"content": json.dumps({
        "suggestions": [{"line": 2, "message": "Use enumerate.", "severity": "SUGGESTION"}]
    })}}]}
    monkeypatch.setattr(r, "_post", lambda *a, **k: payload)
    issues = r.review("for i in range(len(xs)):\n    pass\n", "x.py")
    assert len(issues) == 1
    assert issues[0].message == "Use enumerate."


def test_review_empty_suggestions(monkeypatch):
    r = LLMReviewer()
    payload = {"choices": [{"message": {"content": '{"suggestions": []}'}}]}
    monkeypatch.setattr(r, "_post", lambda *a, **k: payload)
    assert r.review("x = 1\n", "x.py") == []


def test_review_garbage_content_returns_empty(monkeypatch):
    """Garbage content that can't be salvaged -> no issues, no crash."""
    r = LLMReviewer()
    payload = {"choices": [{"message": {"content": "not json"}}]}
    monkeypatch.setattr(r, "_post", lambda *a, **k: payload)
    assert r.review("x = 1\n", "x.py") == []


def test_review_consistency_tags_llm002(monkeypatch):
    """Consistency findings are tagged LLM002, distinct from LLM001."""
    r = LLMReviewer()
    payload = {"choices": [{"message": {"content": json.dumps({
        "suggestions": [{"line": 2, "message": "X does A here, sibling Y does B.",
                         "severity": "SUGGESTION"}]
    })}}]}
    monkeypatch.setattr(r, "_post", lambda *a, **k: payload)
    issues = r.review_consistency("x = 1\ny = 2\n", "x.py", related="  y.py: class Y")
    assert len(issues) == 1
    assert issues[0].code == "LLM002"


def test_review_consistency_no_related_returns_empty(monkeypatch):
    """No sibling context -> no consistency call, no findings."""
    r = LLMReviewer()
    called = []
    monkeypatch.setattr(r, "_post", lambda *a, **k: called.append(a))
    assert r.review_consistency("x = 1\n", "x.py", related="") == []
    assert called == []  # never hit the model


def test_review_consistency_prompt_mentions_siblings(monkeypatch):
    """The consistency prompt is a focused comparison task."""
    from codereview.llm.prompts import CONSISTENCY_PROMPT
    assert "SIBLING" in CONSISTENCY_PROMPT
    assert "deviations" in CONSISTENCY_PROMPT.lower()


def test_check_returns_none_when_reachable(monkeypatch):
    r = LLMReviewer()
    monkeypatch.setattr(r, "_post", lambda *a, **k: {"choices": []})
    assert r.check() is None


def test_check_returns_message_when_unreachable(monkeypatch):
    r = LLMReviewer()
    monkeypatch.setattr(r, "_post", lambda *a, **k: (_ for _ in ()).throw(LLMError("down")))
    assert r.check() == "down"


# ---- _post retry on local cold-start ----

def test_post_retries_local_urlerror_then_succeeds(monkeypatch):
    """Local runtime refusing connections (cold VRAM load) is retried."""
    import urllib.error
    from codereview.llm import reviewer as mod
    r = LLMReviewer()
    r.url = "http://localhost:11434/v1/chat/completions"  # is_local
    calls = {"n": 0}
    sleeps = []

    def flaky_urlopen(req, timeout):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("connection refused")
        class FakeResp:
            def read(self):
                return b'{"choices": [{"message": {"content": "{}"}}]}'
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return FakeResp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(mod.time, "sleep", lambda s: sleeps.append(s))
    payload = r._post([{"role": "user", "content": "ping"}], max_tokens=1)
    assert calls["n"] == 3          # failed twice, succeeded on 3rd
    assert len(sleeps) == 2         # backoff between attempts
    assert sleeps[0] < sleeps[1]    # increasing delay


def test_post_retries_local_urlerror_then_fails(monkeypatch):
    """Persistent local failure still surfaces the unreachable message."""
    import urllib.error
    from codereview.llm import reviewer as mod
    r = LLMReviewer()
    r.url = "http://localhost:11434/v1/chat/completions"  # is_local
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)

    def always_fail(req, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(mod.urllib.request, "urlopen", always_fail)
    with pytest.raises(LLMError) as exc:
        r._post([{"role": "user", "content": "ping"}], max_tokens=1)
    assert "No local model runtime detected" in str(exc.value)


def test_post_does_not_retry_remote(monkeypatch):
    """Remote endpoints fail fast: no retry loop."""
    import urllib.error
    from codereview.llm import reviewer as mod
    r = LLMReviewer()
    r.api_key = "sk-test"  # remote endpoint
    r.url = "https://api.openai.com/v1/chat/completions"
    calls = {"n": 0}

    def always_fail(req, timeout):
        calls["n"] += 1
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(mod.urllib.request, "urlopen", always_fail)
    with pytest.raises(LLMError):
        r._post([{"role": "user", "content": "ping"}], max_tokens=1)
    assert calls["n"] == 1


# ---- ensure_model bootstrap (installer module) ----

def test_ensure_model_already_installed(monkeypatch):
    from codereview.llm.installer import ensure_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: True)
    messages = []
    ensure_model(announce=messages.append)  # no prompt, no download
    assert any("already available" in m for m in messages)


def test_ensure_model_declines_ollama_install(monkeypatch):
    from codereview.llm.installer import ModelInstallError, ensure_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    with pytest.raises(ModelInstallError):
        ensure_model(announce=lambda m: None)


def test_ensure_model_yes_installs_ollama_and_pulls(monkeypatch):
    from codereview.llm.installer import ensure_model
    calls = []
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: False)
    monkeypatch.setattr("codereview.llm.installer.install_ollama",
                        lambda announce: calls.append("install"))
    monkeypatch.setattr("codereview.llm.installer.pick_best_model", lambda: None)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)
    monkeypatch.setattr("codereview.llm.installer.installed_models", lambda: set())
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append("pull"))
    ensure_model(yes=True, announce=lambda m: None)
    assert calls == ["install", "pull"]


def test_ensure_model_declines_model_download(monkeypatch):
    from codereview.llm.installer import ModelInstallError, ensure_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    with pytest.raises(ModelInstallError):
        ensure_model(announce=lambda m: None)


def test_ensure_model_yes_pulls_model(monkeypatch):
    from codereview.llm.installer import ensure_model
    calls = []
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.pick_best_model", lambda: None)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)
    monkeypatch.setattr("codereview.llm.installer.installed_models", lambda: set())
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append("pull"))
    ensure_model(yes=True, announce=lambda m: None)
    assert calls == ["pull"]


def test_ensure_model_pull_failure_raises(monkeypatch):
    import subprocess
    from codereview.llm.installer import ModelInstallError, ensure_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.pick_best_model", lambda: None)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "ollama pull")

    monkeypatch.setattr("codereview.llm.installer.subprocess.run", boom)
    with pytest.raises(ModelInstallError):
        ensure_model(yes=True, announce=lambda m: None)


# ---- embedding progress callback ----

def test_embed_many_reports_progress(monkeypatch):
    """embed_many invokes progress(done, total) once per batch."""
    from codereview.rag.embeddings import EmbeddingClient
    client = EmbeddingClient()
    monkeypatch.setattr(client, "embed", lambda t: [0.0] * 4)
    calls = []
    client.embed_many(["a", "b", "c"], progress=lambda d, t: calls.append((d, t)))
    assert calls == [(3, 3)]


def test_embed_many_no_progress_ok(monkeypatch):
    """embed_many works without a progress callback."""
    from codereview.rag.embeddings import EmbeddingClient
    client = EmbeddingClient()
    monkeypatch.setattr(client, "embed", lambda t: [0.0] * 4)
    assert len(client.embed_many(["a", "b"])) == 2


def test_embed_many_empty_returns_empty(monkeypatch):
    """embed_many([]) returns [] without hitting the network."""
    from codereview.rag.embeddings import EmbeddingClient
    client = EmbeddingClient()
    monkeypatch.setattr(client, "embed", lambda t: (_ for _ in ()).throw(AssertionError))
    assert client.embed_many([]) == []


# ---- ensure_embed_model (installer module) ----

def test_ensure_embed_model_already_installed(monkeypatch):
    from codereview.llm.installer import ensure_embed_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: True)
    messages = []
    ensure_embed_model(announce=messages.append)
    assert any("already available" in m for m in messages)


def test_ensure_embed_model_requires_ollama(monkeypatch):
    from codereview.llm.installer import ModelInstallError, ensure_embed_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: False)
    with pytest.raises(ModelInstallError):
        ensure_embed_model(announce=lambda m: None)


def test_ensure_embed_model_declines_download(monkeypatch):
    from codereview.llm.installer import ModelInstallError, ensure_embed_model
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    with pytest.raises(ModelInstallError):
        ensure_embed_model(announce=lambda m: None)


def test_ensure_embed_model_yes_pulls(monkeypatch):
    from codereview.llm.installer import EMBED_MODEL, ensure_embed_model
    calls = []
    monkeypatch.setattr("codereview.llm.installer.ollama_installed", lambda: True)
    monkeypatch.setattr("codereview.llm.installer.model_pulled", lambda m: False)
    monkeypatch.setattr("codereview.llm.installer._ollama_binary", lambda: "ollama")
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(a[0]))
    ensure_embed_model(yes=True, announce=lambda m: None)
    assert calls == [["ollama", "pull", EMBED_MODEL]]


# ---- _install_ollama platform dispatch (installer module) ----

def test_install_ollama_windows(monkeypatch):
    from codereview.llm.installer import _install_ollama_windows
    calls = []
    monkeypatch.setattr("codereview.llm.installer._download",
                        lambda url, dest, announce: calls.append(("download", url)))
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(("run", a[0])))
    _install_ollama_windows("https://example.com/OllamaSetup.exe", lambda m: None)
    assert calls[0][0] == "download"
    assert calls[1][0] == "run"
    assert calls[1][1][0].endswith("OllamaSetup.exe")


def test_install_ollama_linux(monkeypatch):
    from codereview.llm.installer import _install_ollama_linux
    calls = []
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(a[0]))
    _install_ollama_linux("https://example.com/install.sh", lambda m: None)
    assert calls == [["curl", "-fsSL", "https://example.com/install.sh", "|", "sh"]]


def test_install_ollama_macos(monkeypatch):
    from codereview.llm.installer import _install_ollama_macos
    calls = []
    monkeypatch.setattr("codereview.llm.installer._download",
                        lambda url, dest, announce: calls.append(("download", url)))
    monkeypatch.setattr("codereview.llm.installer.subprocess.run",
                        lambda *a, **k: calls.append(("run", a[0])))
    _install_ollama_macos("https://example.com/Ollama-darwin.zip", lambda m: None)
    assert calls[0][0] == "download"
    assert calls[1][0] == "run"
    assert calls[1][1][0] == "unzip"
    assert calls[1][1][2].endswith("Ollama-darwin.zip")


def test_install_ollama_unsupported_platform(monkeypatch):
    from codereview.llm.installer import ModelInstallError, install_ollama
    monkeypatch.setattr("codereview.llm.installer.sys.platform", "plan9")
    with pytest.raises(ModelInstallError):
        install_ollama(lambda m: None)


def test_download_writes_file(monkeypatch, tmp_path):
    from codereview.llm.installer import _download
    dest = str(tmp_path / "model.bin")

    class FakeResp:
        headers = {"Content-Length": "5"}
        def __init__(self):
            self._chunks = [b"hello", b""]
        def read(self, n):
            return self._chunks.pop(0)
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("codereview.llm.installer.urllib.request.urlopen",
                        lambda url, timeout: FakeResp())
    _download("http://example.com/model", dest, lambda m, **k: None)
    with open(dest, "rb") as fh:
        assert fh.read() == b"hello"


# ---- consistency pre-check (CodebaseIndex structural signature) ----

def _build_index(tmp_path):
    """Build a small index with two sibling detectors + one odd one out."""
    (tmp_path / "base.py").write_text(
        "class Detector:\n"
        "    pass\n"
    )
    (tmp_path / "a.py").write_text(
        "from base import Detector\n"
        "\n"
        "class A(Detector):\n"
        "    def run(self):\n"
        "        return 1\n"
    )
    (tmp_path / "b.py").write_text(
        "from base import Detector\n"
        "\n"
        "class B(Detector):\n"
        "    def run(self):\n"
        "        return 2\n"
    )
    (tmp_path / "c.py").write_text(
        "from base import Detector\n"
        "import json\n"
        "\n"
        "class C(Detector):\n"
        "    def run(self):\n"
        "        return json.dumps({})\n"
    )
    return CodebaseIndex.build(tmp_path, embed=False)


def test_siblings_match_true_when_identical(tmp_path):
    """Siblings with identical imports+bases -> skip the consistency call."""
    idx = _build_index(tmp_path)
    assert idx.siblings_match("a.py") is True
    assert idx.siblings_match("b.py") is True


def test_siblings_match_false_when_import_differs(tmp_path):
    """A sibling with an extra import breaks the match -> run the LLM."""
    idx = _build_index(tmp_path)
    assert idx.siblings_match("c.py") is False


def test_siblings_match_false_without_siblings(tmp_path):
    """No siblings -> conservative False (run the LLM)."""
    from codereview.rag import CodebaseIndex
    (tmp_path / "solo.py").write_text("x = 1\n")
    idx = CodebaseIndex.build(tmp_path, embed=False)
    assert idx.siblings_match("solo.py") is False


def test_structural_signature_contains_imports_and_bases(tmp_path):
    """The signature is (imports, bases) — the file's structural pattern."""
    idx = _build_index(tmp_path)
    imports, bases = idx.structural_signature("a.py")
    assert "base" in imports
    assert "Detector" in bases


def test_sibling_files_excludes_self(tmp_path):
    """sibling_files returns other files sharing a base, never itself."""
    idx = _build_index(tmp_path)
    sibs = idx.sibling_files("a.py")
    assert "a.py" not in sibs
    assert "b.py" in sibs
    assert "c.py" in sibs


# ---- RAG index disk cache ----

def test_cache_roundtrip_identical(tmp_path):
    """A cached build returns an identical index (chunks, graph, symbols)."""
    idx1 = _build_index(tmp_path)
    idx2 = CodebaseIndex.build(tmp_path, embed=False)  # cache hit
    assert [c.symbol for c in idx1.chunks] == [c.symbol for c in idx2.chunks]
    assert idx1.imports == idx2.imports
    assert idx1.bases == idx2.bases
    assert idx1.module_files == idx2.module_files
    assert idx1.symbols.keys() == idx2.symbols.keys()


def test_cache_written_to_dot_codereview(tmp_path):
    """The cache lands in <root>/.codereview/rag-index.json."""
    _build_index(tmp_path)
    assert (tmp_path / ".codereview" / "rag-index.json").exists()


def test_cache_invalidated_on_file_change(tmp_path):
    """Touching a file invalidates the cache (mtime mismatch)."""
    _build_index(tmp_path)
    (tmp_path / "a.py").write_text(
        "from base import Detector\n"
        "\n"
        "class A(Detector):\n"
        "    def run(self):\n"
        "        return 99\n"  # changed
    )
    idx = CodebaseIndex.build(tmp_path, embed=False)
    assert len(idx.chunks) == 4  # rebuilt (4 files), not stale
    assert idx.symbols["A"].body == "methods: run(self)"  # fresh content


def test_cache_invalidated_on_new_file(tmp_path):
    """Adding a file changes the file set -> cache is stale."""
    _build_index(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    idx = CodebaseIndex.build(tmp_path, embed=False)
    assert len(idx.chunks) == 4  # includes the new file


def test_cache_corrupt_returns_none(tmp_path):
    """Corrupt JSON -> load returns None (caller rebuilds)."""
    from codereview.rag.cache import load
    _build_index(tmp_path)
    cache_file = tmp_path / ".codereview" / "rag-index.json"
    cache_file.write_text("not json", encoding="utf-8")
    assert load(tmp_path, ["a.py", "b.py", "base.py"]) is None


def test_cache_use_cache_false_skips_disk(tmp_path):
    """use_cache=False never writes the cache file."""
    CodebaseIndex.build(tmp_path, embed=False, use_cache=False)
    assert not (tmp_path / ".codereview" / "rag-index.json").exists()