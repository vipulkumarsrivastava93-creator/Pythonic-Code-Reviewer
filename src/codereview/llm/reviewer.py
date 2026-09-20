"""LLM reviewer adapter: optional, flag-gated, local-first.

Talks to any **OpenAI-compatible** chat-completions endpoint over HTTP using
only the stdlib (`urllib.request`), so the core package stays dependency-free.

Two targets are supported by one code path:

- **Local (default):** Ollama or LM Studio on `localhost`. Code never leaves
  the machine. This is the privacy-preserving default.
- **Remote (opt-in):** any OpenAI-compatible API (Claude, GPT, ...) via the
  user's own endpoint + key. The user must explicitly opt in with
  `CODEREVIEW_LLM_URL` / `CODEREVIEW_LLM_API_KEY`; there is no bundled key.

The LLM is the *interpreter, not the brain* (DESIGN.md §13.3): it receives a
compact AST summary + source lines for a target and returns a short list of
actionable suggestions. It never *discovers* issues from raw code alone — the
deterministic detectors carry that load.

If no runtime is reachable, the tool degrades to static-only with a clear
banner (DESIGN.md §12.6).
"""

from __future__ import annotations

import ast
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from codereview.llm.installer import DEFAULT_MODEL, ModelInstallError, pick_best_model
from codereview.llm.prompts import (
    CONSISTENCY_PROMPT,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from codereview.report import Category, Issue, Severity

# Rule id for LLM-sourced findings. Distinct from PY*/DES* so LLM findings are
# identifiable and suppressible via `# noqa: LLM001`.
LLM_RULE_CODE = "LLM001"
# Rule id for the separate consistency-comparison path (--rag-embed).
# Distinct so consistency findings are suppressible via `# noqa: LLM002`.
LLM_RULE_CODE_CONSISTENCY = "LLM002"

DEFAULT_LOCAL_URL = "http://localhost:11434/v1/chat/completions"  # Ollama

_TIMEOUT_SECONDS = 180.0  # reasoning models (R1) generate long thinking traces
_MAX_SUGGESTIONS = 5
_RETRY_ATTEMPTS = 3  # local cold-start: Ollama refuses while loading to VRAM
_RETRY_DELAY_SECONDS = 2.0


class LLMError(Exception):
    """Raised when the LLM runtime is unreachable or returns garbage."""


@dataclass
class LLMReviewer:
    """A thin OpenAI-compatible chat-completions client.

    Resolution order for the endpoint:
      1. `CODEREVIEW_LLM_URL` env var (explicit remote/local override).
      2. `CODEREVIEW_LLM_API_KEY` env var present -> OpenAI-compatible remote
         (defaults to https://api.openai.com/v1/chat/completions).
      3. Local Ollama on `localhost:11434`.
    """

    url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = _TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        self.url = self.url or os.environ.get("CODEREVIEW_LLM_URL", "")
        self.api_key = self.api_key or os.environ.get("CODEREVIEW_LLM_API_KEY", "")
        self.model = self.model or os.environ.get("CODEREVIEW_LLM_MODEL", "")
        if not self.model:
            # Auto-pick the best installed model; fall back to the default.
            self.model = pick_best_model() or DEFAULT_MODEL
        if not self.url:
            if self.api_key:
                self.url = "https://api.openai.com/v1/chat/completions"
            else:
                self.url = DEFAULT_LOCAL_URL

    @property
    def is_local(self) -> bool:
        """True when talking to a local runtime (no API key, localhost URL)."""
        return not self.api_key and "localhost" in self.url

    def check(self) -> str | None:
        """Return an error message if the runtime is unreachable, else None."""
        try:
            self._post([{"role": "user", "content": "ping"}], max_tokens=1)
            return None
        except LLMError as exc:
            return str(exc)

    def review(self, source: str, path: str = "<string>",
               static_issues: list[Issue] | None = None,
               focus: str = "design",
               related: str = "") -> list[Issue]:
        """Ask the model for suggestions on `source`; parse into `Issue`s.

        `static_issues` (optional) are the deterministic findings already
        found for this file. They are fed to the model so it knows what is
        already covered and does not repeat it.

        `focus` selects the review lens: "design" (class designs) or
        "logic" (correctness/edge cases).

        `related` (optional) is pre-rendered RAG context: related chunks
        from the same codebase. Empty by default — the prompt is unchanged
        when RAG is not in use.

        Raises `LLMError` if the runtime is unreachable or the response cannot
        be parsed. Returns an empty list when the model reports no improvement.
        """
        prompt = _build_prompt(source, path, static_issues, focus, related)
        payload = self._post(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.2,
        )
        content = _extract_content(payload)
        return _parse_suggestions(content, path, source, _stripped_lines(source))

    def review_consistency(self, source: str, path: str = "<string>",
                           related: str = "") -> list[Issue]:
        """Compare `source` against its siblings; return deviations as LLM002.

        A SEPARATE, focused task from `review()`: the model compares the
        file against sibling code and reports ONLY concrete deviations. The
        prompt is standalone (no review focus, no static issues) so the
        sibling context cannot corrupt the normal review.

        Returns an empty list when the model finds no deviations.
        """
        if not related:
            return []
        summary = _summarize(source)
        body = _strip_imports(source)
        prompt = CONSISTENCY_PROMPT.format(
            path=path,
            summary=summary,
            related=related,
            source=body,
        )
        payload = self._post(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.2,
        )
        content = _extract_content(payload)
        return _parse_suggestions(content, path, source, _stripped_lines(source),
                                  code=LLM_RULE_CODE_CONSISTENCY)

    def _post(self, messages: list[dict], *, max_tokens: int, temperature: float = 0.0) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.url, data=body, headers=headers, method="POST")

        # Local runtimes (Ollama) refuse connections while cold-loading a
        # model into VRAM on first use. Retry with backoff so a cold start
        # doesn't look like a hard failure. Remote endpoints are not retried.
        attempts = _RETRY_ATTEMPTS if self.is_local else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
                raise LLMError(f"LLM endpoint returned HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt + 1 < attempts:
                    time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise LLMError(_unreachable_message(self.url)) from exc
            except TimeoutError as exc:
                if attempt + 1 < attempts:
                    time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise LLMError(
                    f"LLM request timed out after {self.timeout:.0f}s. "
                    "Reasoning models (R1) are slow; try again or use a faster model."
                ) from exc
            except OSError as exc:
                if attempt + 1 < attempts:
                    time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
                    continue
                raise LLMError(_unreachable_message(self.url)) from exc
            except json.JSONDecodeError as exc:
                raise LLMError("LLM endpoint returned non-JSON response") from exc
        raise LLMError(_unreachable_message(self.url))  # pragma: no cover


def check_runtime() -> str | None:
    """Convenience: probe the configured runtime; return error message or None."""
    return LLMReviewer().check()


def review_with_llm(source: str, path: str = "<string>",
                    static_issues: list[Issue] | None = None,
                    focuses: tuple[str, ...] = ("design", "logic"),
                    related: str = "") -> list[Issue]:
    """Review `source` with the given focuses and merge the results.

    Runs one LLM call per focus (default: design + logic) and merges the
    findings. Each call is small and parallelizable, so running both is
    nearly free on GPU.

    `related` (optional) is pre-rendered RAG context passed to each focus.
    """
    reviewer = LLMReviewer()
    merged: list[Issue] = []
    for focus in focuses:
        merged.extend(reviewer.review(source, path, static_issues, focus, related))
    return merged


def _unreachable_message(url: str) -> str:
    if "localhost" in url:
        return (
            "No local model runtime detected.\n"
            "  → Install Ollama (https://ollama.com) then:\n"
            "      ollama pull deepseek-r1:7b\n"
            "  Or set CODEREVIEW_LLM_URL to any OpenAI-compatible endpoint."
        )
    return (
        "LLM endpoint unreachable. Check CODEREVIEW_LLM_URL and "
        "CODEREVIEW_LLM_API_KEY."
    )


def _build_prompt(source: str, path: str,
                  static_issues: list[Issue] | None = None,
                  focus: str = "design",
                  related: str = "") -> str:
    """Assemble the user prompt for a file review.

    Import statements and docstrings are stripped from the source (replaced
    with blank lines) so the model cannot comment on them — the static
    detectors already cover import placement, and a small model tends to
    fixate on imports and read docstrings as code.

    `related` (optional) is pre-rendered RAG context injected into the
    prompt so the model understands the file's role in the codebase.
    """
    summary = _summarize(source)
    body = _strip_imports(source)
    return build_user_prompt(
        path=path,
        summary=summary,
        source=body,
        static_issues=static_issues,
        focus=focus,
        related=related,
    )


def _strip_imports(source: str) -> str:
    """Replace imports and docstrings with blank lines, preserving line numbers.

    The model cannot comment on lines it cannot see: the static detectors
    already handle import placement (PY016), and docstrings are prose, not
    code — a small model reads them as code (e.g. reports "use is None" for
    a docstring containing '== None').
    """
    stripped = _stripped_lines(source)
    if not stripped:
        return source
    lines = source.splitlines()
    for lineno in stripped:
        if 1 <= lineno <= len(lines):
            lines[lineno - 1] = ""
    return "\n".join(lines)


def _stripped_lines(source: str) -> set[int]:
    """Line numbers of imports and docstrings (blanked before sending to the model)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            lines.add(node.lineno)
        elif _is_docstring(node):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def _is_docstring(node: ast.AST) -> bool:
    """True if `node` is a bare string statement (docstring or dead string)."""
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _summarize(source: str) -> str:
    """A cheap structural summary of the file (functions/classes only).

    Imports are deliberately excluded: the model tends to fixate on them and
    produce noise ("remove unused import"), and the static detectors already
    cover import placement.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "(unparseable)"
    parts: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parts.append(f"def {node.name} (line {node.lineno})")
        elif isinstance(node, ast.ClassDef):
            parts.append(f"class {node.name} (line {node.lineno})")
    return "\n".join(parts) if parts else "(no top-level definitions)"


def _extract_content(payload: dict) -> str:
    """Pull the assistant text out of an OpenAI-compatible response.

    Reasoning models (DeepSeek-R1) return a `reasoning` field alongside
    `content`; we only want the final answer, so `content` is read directly.
    """
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError("LLM response missing 'choices[0].message.content'") from exc


def _parse_suggestions(content: str, path: str, source: str = "",
                       stripped_lines: set[int] | None = None,
                       code: str = LLM_RULE_CODE) -> list[Issue]:
    """Parse the model's JSON into `Issue`s. Tolerant of markdown fences.

    Issues whose `line` does not point at a real statement in `source` are
    dropped (hallucination filter): a small model sometimes invents line
    numbers or references code that does not exist.

    Issues on `stripped_lines` (imports blanked out before sending) are also
    dropped: the model cannot see those lines, so any finding there is a
    hallucination.

    `code` tags the findings (default LLM001; LLM002 for consistency).

    Robustness: small models frequently wrap the JSON in ```json fences, add
    trailing commas, or truncate the output at max_tokens. We handle all three:
    strip fences, extract the JSON object between the first `{` and last `}`,
    and if that still fails, salvage individual suggestion objects.
    """
    stripped_lines = stripped_lines or set()
    text = _extract_json_object(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to salvaging individual suggestion objects.
        return _salvage_suggestions(content, source, stripped_lines, code)
    if not isinstance(data, dict):
        return []  # not a JSON object -> nothing usable
    raw = data.get("suggestions", [])
    if not isinstance(raw, list):
        return []  # 'suggestions' not a list -> nothing usable

    valid_lines = _statement_lines(source)
    issues: list[Issue] = []
    for item in raw[:_MAX_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        line = item.get("line")
        message = item.get("message")
        if not isinstance(line, int) or not isinstance(message, str) or not message.strip():
            continue
        if line in stripped_lines:
            continue  # import line the model cannot see
        if valid_lines and line not in valid_lines:
            continue  # hallucinated line number
        severity = _parse_severity(item.get("severity"))
        issues.append(Issue(
            code=code,
            category=Category.DESIGN,
            severity=severity,
            message=message.strip(),
            line=line,
        ))
    return issues


def _extract_json_object(content: str) -> str:
    """Strip fences and extract the JSON object between first `{` and last `}`.

    Handles ```json fences, leading/trailing prose, and trailing commas before
    the closing brace (a common small-model mistake).
    """
    text = content.strip()
    # Strip a ```json ... ``` fence if present.
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Extract the JSON object between the first { and last }.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    # Remove trailing commas before } or ] (small models add them).
    text = _fix_trailing_commas(text)
    return text


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ] (invalid JSON, common in LLM output)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _salvage_suggestions(content: str, source: str,
                         stripped_lines: set[int] | None = None,
                         code: str = LLM_RULE_CODE) -> list[Issue]:
    """Best-effort parse of truncated/malformed output via regex.

    Matches `{"line": N, "message": "...", "severity": "..."}` objects even
    when the surrounding JSON is broken (truncated at max_tokens, etc.).
    """
    stripped_lines = stripped_lines or set()
    valid_lines = _statement_lines(source)
    issues: list[Issue] = []
    pattern = re.compile(
        r'"line"\s*:\s*(\d+)\s*,\s*"message"\s*:\s*"((?:[^"\\]|\\.)*)"'
        r'(?:\s*,\s*"severity"\s*:\s*"([^"]*)")?'
    )
    for match in pattern.finditer(content):
        line = int(match.group(1))
        message = match.group(2).encode().decode("unicode_escape", errors="replace")
        severity = _parse_severity(match.group(3))
        if not message.strip():
            continue
        if line in stripped_lines:
            continue
        if valid_lines and line not in valid_lines:
            continue
        issues.append(Issue(
            code=code,
            category=Category.DESIGN,
            severity=severity,
            message=message.strip(),
            line=line,
        ))
        if len(issues) >= _MAX_SUGGESTIONS:
            break
    return issues


def _statement_lines(source: str) -> set[int]:
    """Line numbers that contain real statements (for hallucination filtering)."""
    if not source:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    lines: set[int] = set()
    for node in ast.walk(tree):
        lineno = getattr(node, "lineno", None)
        if isinstance(lineno, int):
            lines.add(lineno)
    return lines


def _parse_severity(value: Any) -> Severity:
    try:
        return Severity(str(value).upper())
    except ValueError:
        return Severity.SUGGESTION


__all__ = [
    "DEFAULT_LOCAL_URL",
    "LLMError",
    "LLMReviewer",
    "LLM_RULE_CODE",
    "LLM_RULE_CODE_CONSISTENCY",
    "check_runtime",
    "review_with_llm",
]