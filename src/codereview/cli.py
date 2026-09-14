"""Command-line interface: review a Python file and print a report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from codereview.orchestrator import OFFLINE
from codereview.report import Report

_RESET = "\x1b[0m"
_BOLD_MAGENTA = "\x1b[1;35m"
_BOLD_CYAN = "\x1b[1;36m"
_BOLD_WHITE = "\x1b[1;37m"
_BOLD_UNDERLINE_BLUE = "\x1b[1;4;34m"
_DIM = "\x1b[2m"
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
    parser.add_argument("path", help="Path to a Python file or (with --recursive) a directory.")
    parser.add_argument("-r", "--recursive", "--dir", action="store_true",
                        dest="recursive",
                        help="If PATH is a directory, recursively review every *.py file under it.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    parser.add_argument("--no-links", action="store_true",
                        help="Disable clickable links (plain path:line text).")
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


def _review_paths(paths: list[Path], *, links: bool, to_json: bool) -> int:
    """Review each path, printing reports. Returns 0 if everything succeeds.

    Output order: clean files first, then files with findings, then a summary
    of suggestion/warning counts. JSON mode prints one JSON object per file in
    path order (no grouping).
    """
    failed = False
    reports: list[tuple[Path, Report]] = []
    for path in paths:
        try:
            report = OFFLINE.review_file(path)
        except SyntaxError as exc:
            print(f"Invalid Python ({path}): {exc}", file=sys.stderr)
            failed = True
            continue
        except OSError as exc:
            print(f"Error reading {path}: {exc}", file=sys.stderr)
            failed = True
            continue

        if to_json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            reports.append((path, report))

    if not to_json:
        _print_grouped(reports, links=links)
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    raw = Path(args.path)
    if args.recursive:
        if not raw.is_dir():
            print(f"Error: --recursive requires a directory: {raw}", file=sys.stderr)
            return 1
        paths = sorted(p for p in raw.rglob("*.py") if p.is_file())
        if not paths:
            print(f"No .py files found under {raw}", file=sys.stderr)
            return 0
        return _review_paths(paths, links=not args.no_links, to_json=args.json)

    if not raw.is_file():
        print(f"Error: no such file: {raw}", file=sys.stderr)
        return 1

    return _review_paths([raw], links=not args.no_links, to_json=args.json)


if __name__ == "__main__":
    sys.exit(main())