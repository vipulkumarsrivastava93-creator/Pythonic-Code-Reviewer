"""Command-line interface: review a Python file and print a report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from codereview.orchestrator import OFFLINE
from codereview.report import Report

try:
    from codereview.llm import LLMError, ModelInstallError, ensure_model, review_with_llm
except ImportError:  # pragma: no cover - llm package is always present
    LLMError = None  # type: ignore[assignment,misc]
    ModelInstallError = None  # type: ignore[assignment,misc]
    ensure_model = None  # type: ignore[assignment]
    review_with_llm = None  # type: ignore[assignment]

_RESET = "\x1b[0m"
_BOLD_MAGENTA = "\x1b[1;35m"
_BOLD_CYAN = "\x1b[1;36m"
_BOLD_WHITE = "\x1b[1;37m"
_BOLD_UNDERLINE_BLUE = "\x1b[1;4;34m"
_DIM = "\x1b[2m"

# Files under this many lines are skipped for LLM review: there is nothing
# meaningful to review, and tiny files (e.g. a docstring + import) invite
# hallucinated findings about missing definitions.
MIN_LLM_LINES = 10
_SEVERITY_COLORS = {
    "INFO": "\x1b[90m",
    "SUGGESTION": "\x1b[33m",
    "WARNING": "\x1b[1;31m",
}


def use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def use_links() -> bool:
    """Emit OSC 8 hyperlinks only in an interactive terminal, unless disabled.

    Piped output and CI capture stdout, so `isatty()` is False there and links
    are skipped automatically. Set CODEREVIEW_LINKS=off (or use --no-links) on
    terminals that mangle OSC 8 sequences (some IDE panes).
    """
    if os.environ.get("CODEREVIEW_LINKS", "").lower() == "off":
        return False
    return sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    return f"{color}{text}{_RESET}"


def _style_code(code: str) -> str:
    return _c(code, _BOLD_CYAN)


def _style_severity(sev) -> str:
    return _c(str(sev), _SEVERITY_COLORS.get(str(sev), ""))


def _style_loc(line: int) -> str:
    return _c(f"L{line}", _BOLD_WHITE)


def _style_link(text: str) -> str:
    return _c(text, _BOLD_UNDERLINE_BLUE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codereview",
        description="Local Pythonic + design code reviewer (offline).",
    )
    parser.add_argument("path", nargs="?",
                        help="Path to a Python file or (with --recursive) a directory.")
    parser.add_argument("-r", "--recursive", "--dir", action="store_true",
                        dest="recursive",
                        help="If PATH is a directory, recursively review every *.py file under it.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    parser.add_argument("--no-links", action="store_true",
                        help="Disable clickable links (plain path:line text).")
    parser.add_argument("--llm", action="store_true",
                        help="Also run an LLM review (local Ollama by default; see README). "
                             "Degrades to static-only if no runtime is reachable.")
    parser.add_argument("--setup", action="store_true",
                        help="Install the local LLM runtime + model (Ollama), then exit.")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="With --llm/--setup: auto-confirm the model download prompt "
                             "(still prints what it is doing).")
    parser.add_argument("--workers", type=int, default=4,
                        help="With --llm: number of parallel LLM requests (default 4). "
                             "Ollama batches these on the GPU.")
    return parser


def _clickable(text: str, uri: str, enabled: bool) -> str:
    """Wrap `text` in an OSC 8 terminal hyperlink targeting `uri`."""
    if not enabled:
        return text
    return f"\x1b]8;;{uri}\x1b\\{text}\x1b]8;;\x1b\\"


def _editor_uri(path: str, line: int) -> str:
    """Build a clickable OS/editor URI for `path` at `line`.

    Uses pathlib.Path.as_uri() for a standards-correct file:/// URI on every
    platform. The vscode scheme needs the explicit 'file' form:
    vscode://file/<abs-path>:<line>.

    Defaults to VS Code (the primary editor); override with the
    CODEREVIEW_EDITOR env var (e.g. "file" for plain file:// links).
    """
    file_uri = Path(path).resolve().as_uri()
    editor = os.environ.get("CODEREVIEW_EDITOR", "vscode")
    if editor == "vscode":
        # file_uri -> file:///C:/x/y.py ; build vscode://file/C:/x/y.py:line
        drive_path = file_uri[len("file://"):]
        return f"vscode://file{drive_path}:{line}"
    return file_uri


def _source_line(report: Report, issue) -> str | None:
    """Return the offending source line (None if unavailable/out of range)."""
    try:
        lines = report.source.split("\n")
        if 1 <= issue.line <= len(lines):
            return lines[issue.line - 1]
    except Exception:
        return None
    return None


def display(report: Report, *, links: bool | None = None) -> None:
    """Print a human-readable report with spacing, links, and color."""
    issues = report.issues
    if not issues:
        print("Check complete, good code!")
        return

    colored = use_color()
    clickable = links if links is not None else use_links()
    fname = Path(report.path).name

    current_category = None
    for issue in issues:
        if issue.category != current_category:
            if current_category is not None:
                print("\n")
            current_category = issue.category
            header = str(current_category).upper()
            print(_c(f"{header}:", _BOLD_MAGENTA) if colored else f"{header}:")
            print()

        code = _style_code(issue.code) if colored else issue.code
        sev = _style_severity(issue.severity) if colored else str(issue.severity)
        loc = _style_loc(issue.line) if colored else f"L{issue.line}"
        link_text = f"{fname}:{issue.line}"
        link_uri = _editor_uri(report.path, issue.line)
        link = f"{_style_link(link_text)}" if colored else link_text
        if clickable:
            link = _clickable(link, link_uri, True)

        print(f"  {code}  {sev}  {loc}  {link}")
        print(f"      {issue.message}")
        culprit = _source_line(report, issue)
        if culprit is not None and culprit.strip():
            if colored:
                print(f"      {_c(f'{issue.line} | {culprit}', _DIM)}")
            else:
                print(f"      {issue.line} | {culprit}")
        print()


def _ensure_llm_ready(yes: bool) -> bool:
    """Ensure the local model is available for --llm. Returns True if ready.

    Prints every step to stderr. If the user declines, interrupts, or the
    runtime is missing, prints a clear banner and returns False so the caller
    falls back to static-only review.
    """
    if ensure_model is None:  # pragma: no cover - llm package always present
        return False
    try:
        ensure_model(yes=yes,
                    announce=lambda msg, **kw: print(msg, file=sys.stderr, **kw))
        return True
    except ModelInstallError as exc:
        print(f"LLM unavailable: {exc}", file=sys.stderr)
        return False
    except KeyboardInterrupt:
        print("\nModel download cancelled. Reviewing with static analysis only.",
              file=sys.stderr)
        return False


def _review_one(path: Path, *, use_llm: bool) -> tuple[Path, Report] | tuple[Path, str]:
    """Review a single file: static always, LLM if requested.

    Returns (path, Report) on success, or (path, error_message) on failure.
    """
    try:
        report = OFFLINE.review_file(path)
    except SyntaxError as exc:
        return path, f"Invalid Python ({path}): {exc}"
    except OSError as exc:
        return path, f"Error reading {path}: {exc}"

    if use_llm:
        # Skip tiny files: nothing meaningful to review, and they invite
        # hallucinated findings (e.g. "missing main" on a docstring+import).
        if len(report.source.splitlines()) < MIN_LLM_LINES:
            return path, report
        try:
            llm_issues = review_with_llm(report.source, str(path),
                                         static_issues=report.issues)
            report.extend(llm_issues)
            report.dedupe()
            report.sort()
        except LLMError as exc:
            return path, f"LLM unavailable: {exc}"

    return path, report


def _review_paths(paths: list[Path], *, links: bool, to_json: bool, use_llm: bool = False,
                  yes: bool = False, workers: int = 4) -> int:
    """Review each path, printing reports. Returns 0 if everything succeeds.

    Output order: clean files first, then files with findings, then a summary
    of suggestion/warning counts. JSON mode prints one JSON object per file in
    path order (no grouping).

    When `use_llm` is set, the LLM calls run in parallel (up to `workers`
    concurrent requests) so Ollama's GPU batching can process them together.
    In the parallel path, each file's report is printed as soon as it
    completes (streaming), so the user sees progress instead of waiting for
    all files to finish.
    """
    failed = False
    llm_available = True
    reports: list[tuple[Path, Report]] = []

    if use_llm:
        llm_available = _ensure_llm_ready(yes)

    if use_llm and llm_available and len(paths) > 1 and workers > 1:
        # Parallel path: static review is instant; the LLM calls dominate.
        # Stream each file's report as it completes.
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_review_one, p, use_llm=True): p for p in paths}
            for fut in as_completed(futures):
                path, result = fut.result()
                if isinstance(result, Report):
                    if to_json:
                        print(json.dumps(result.to_dict(), indent=2))
                    else:
                        print(f"── {path} ──")
                        display(result, links=links)
                    reports.append((path, result))
                else:
                    print(result, file=sys.stderr)
                    failed = True
    else:
        # Sequential path (single file, no LLM, or LLM unavailable).
        for path in paths:
            result = _review_one(path, use_llm=use_llm and llm_available)
            if isinstance(result[1], Report):
                reports.append((path, result[1]))
            else:
                print(result[1], file=sys.stderr)
                failed = True

    if to_json:
        # JSON mode: print in deterministic path order (already streamed above
        # in the parallel path, so only the sequential path reaches here).
        if not (use_llm and llm_available and len(paths) > 1 and workers > 1):
            for path, report in reports:
                print(json.dumps(report.to_dict(), indent=2))
    else:
        if not (use_llm and llm_available and len(paths) > 1 and workers > 1):
            _print_grouped(reports, links=links)
        else:
            _print_summary([(p, r) for p, r in reports if not r.issues],
                           [(p, r) for p, r in reports if r.issues])
    return 1 if failed else 0


def _print_grouped(reports: list[tuple[Path, Report]], *, links: bool) -> None:
    """Print clean files first, then files with findings, then a summary."""
    clean = [(p, r) for p, r in reports if not r.issues]
    dirty = [(p, r) for p, r in reports if r.issues]

    for path, report in clean:
        print(f"── {path} ──")
        display(report, links=links)

    for path, report in dirty:
        print(f"── {path} ──")
        display(report, links=links)

    if reports:
        _print_summary(clean, dirty)


def _print_summary(clean: list, dirty: list) -> None:
    """Print a final summary of clean files and suggestion/warning counts."""
    suggestions = sum(
        1 for _, r in dirty for i in r.issues if i.severity.value == "SUGGESTION"
    )
    warnings = sum(
        1 for _, r in dirty for i in r.issues if i.severity.value == "WARNING"
    )
    infos = sum(
        1 for _, r in dirty for i in r.issues if i.severity.value == "INFO"
    )

    print()
    print("── Summary ──")
    print(f"  Files reviewed : {len(clean) + len(dirty)}")
    print(f"  Clean files   : {len(clean)}")
    print(f"  Files with issues: {len(dirty)}")
    print(f"  Suggestions   : {suggestions}")
    print(f"  Warnings      : {warnings}")
    if infos:
        print(f"  Info          : {infos}")


def _cmd_setup(yes: bool) -> int:
    """Install the local LLM runtime + model (no file needed)."""
    if ensure_model is None:  # pragma: no cover - llm package always present
        print("LLM package unavailable.", file=sys.stderr)
        return 1
    try:
        ensure_model(yes=yes, force_menu=True,
                    announce=lambda msg, **kw: print(msg, file=sys.stderr, **kw))
        print("Setup complete. Run 'codereview --llm <file>' to review with the LLM.")
        return 0
    except ModelInstallError as exc:
        print(f"Setup incomplete: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nSetup cancelled by user.", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.setup:
        return _cmd_setup(args.yes)

    if args.path is None:
        build_parser().print_usage(sys.stderr)
        print("codereview: error: a path or --setup is required", file=sys.stderr)
        return 2

    raw = Path(args.path)
    if args.recursive:
        if not raw.is_dir():
            print(f"Error: --recursive requires a directory: {raw}", file=sys.stderr)
            return 1
        paths = sorted(p for p in raw.rglob("*.py") if p.is_file())
        if not paths:
            print(f"No .py files found under {raw}", file=sys.stderr)
            return 0
        return _review_paths(paths, links=not args.no_links, to_json=args.json,
                             use_llm=args.llm, yes=args.yes, workers=args.workers)

    if not raw.is_file():
        print(f"Error: no such file: {raw}", file=sys.stderr)
        return 1

    return _review_paths([raw], links=not args.no_links, to_json=args.json,
                         use_llm=args.llm, yes=args.yes, workers=args.workers)


if __name__ == "__main__":
    sys.exit(main())