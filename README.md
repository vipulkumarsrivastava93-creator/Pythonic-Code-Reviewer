# CodeReview Agent

A **local, dependency-free** code reviewer for Python that answers the question linters can't:

> *"This code works — but is there a more Pythonic or better-designed way to write it?"*

It deliberately layers **on top of** deterministic tools like Ruff, Pylint, and mypy. Those tools
catch hard errors and style violations; CodeReview adds **judgment** — idiomatic constructs and
low-level design signals — using only Python's standard library.

---

## What it does

CodeReview parses your source with the stdlib `ast` module and runs a set of **detectors** that
flag two kinds of issues:

| Category | Concern | Examples |
|---|---|---|
| **Pythonic** (`PY…`) | Idiomatic constructs | list comprehensions, `enumerate()`, `dict.get()`, `is None`, `defaultdict`, f-strings, `with open(...)`, top-level imports |
| **Design** (`DES…`) | Low-level design | large classes, too many `__init__` params, duplicated blocks/methods, excessive nesting, nested functions |

Each finding is reported with a **rule id**, a **severity** (`INFO` / `SUGGESTION` / `WARNING`),
the offending **line**, and a **clickable link** that jumps straight to that line in your editor.

### Example output

```
── test/sample_bad.py ──
PYTHONIC:
  PY001  SUGGESTION  L3  sample_bad.py:3
      Use a list comprehension instead of a for-loop with append.
      3 | result = []
```

The `sample_bad.py:3` link is an OSC 8 terminal hyperlink — click it to jump to line 3 in VS Code.

---

## Installation

Requires **Python 3.9+**. No runtime dependencies.

```bash
# from the project root
pip install -e .
```

This installs the `codereview` console command. (You can also run it without installing via
`python -m codereview`, which works from the project root.)

---

## Usage

### Review a single file

```bash
codereview path/to/file.py
```

### Review a whole project (recursive)

```bash
codereview -r path/to/project
```

`-r` / `--recursive` walks the directory and reviews every `*.py` file under it, printing one
report per file.

### Options

| Flag | Description |
|---|---|
| `-r`, `--recursive`, `--dir` | Treat `path` as a directory and review every `*.py` under it |
| `--json` | Print the report as JSON (for scripting / CI) |
| `--no-links` | Disable clickable links (plain `path:line` text) |

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CODEREVIEW_EDITOR` | `vscode` | Editor scheme for jump links. `vscode` → `vscode://file/...:line`; `file` → plain `file:///` links |
| `CODEREVIEW_LINKS` | *(on)* | Set to `off` to disable OSC 8 hyperlinks (e.g. terminals that mangle them) |
| `NO_COLOR` | *(off)* | Disable ANSI color output |

> Links are emitted **only in an interactive terminal** (`stdout` is a TTY). Piped output and CI
> automatically get plain `path:line` text.

---

## Suppressing findings with `# noqa`

Sometimes a finding is a deliberate exception — a pattern you know is fine in context. You can
suppress it with a `# noqa` comment on the offending line, Ruff/Flake8-style:

```python
def f(xs):
    if xs == None:  # noqa: PY007 - deliberate: sentinel check on legacy API
        pass
```

Two forms are supported:

| Form | Effect |
|---|---|
| `# noqa` | Suppresses **all** findings on that line |
| `# noqa: PY007, DES003` | Suppresses **only** the listed rule ids on that line |

Notes:

- Suppression is **line-scoped** — a `# noqa` only affects findings reported on that exact line.
- Trailing explanation text after the codes is allowed (e.g. `# noqa: PY007 - reason`), matching
  Ruff/Flake8 behavior.
- Use it sparingly: prefer fixing the underlying issue. `# noqa` is meant for cases that genuinely
  can't be rectified (or where the finding is a false positive for your context).

---

## Roadmap: on-device LLM review (planned)

The static analyzers are instant and offline. The longer-term plan is to add a **small local
model** for deeper, subjective review — running **entirely on your machine**, never sending code
to any online AI platform. That privacy guarantee is the core of this tool.

The intended design (see `DESIGN.md`):

- A local runtime such as **Ollama** (or LM Studio) serves a small model like
  `qwen2.5-coder:1.5b` over `localhost`.
- Code is sent **only** to that local runtime — never to a hosted service.
- The model is **opt-in**: if no local runtime is detected, the tool degrades to static-only
  analysis with a clear banner.
- The model is **fetched by the user at runtime** (`ollama pull ...`), never bundled in the
  package.

> **Privacy boundary:** no code ever leaves your machine. There is no online AI integration and
> none is planned.

---

## Development

```bash
pip install -e ".[dev]"   # installs pytest
pytest                    # run the test suite
```

The project is organized as:

```
src/codereview/
  cli.py            # argument parsing, report formatting, clickable links
  orchestrator.py   # review flow (parse AST -> run detectors -> Report)
  report.py         # Issue / Report data model
  rules.py          # central rule registry (PY001…, DES001…)
  analyzers/        # AST detectors
    detectors/      # individual detectors (list comp, enumerate, nesting, …)
  llm/              # (planned) local on-device model adapter (Ollama)
```

---

## Design notes

- **Local-first & private.** Analysis runs entirely on your machine; no code is sent anywhere by
  default. The planned LLM path uses a **local on-device model** (e.g. via Ollama) bound to
  `localhost` — never an online AI platform.
- **Fast.** Static analysis is a single `ast` pass with no network — well under 150 ms for a
  1k-line file.
- **Zero dependencies.** Everything uses the Python standard library.
- See `DESIGN.md` for the full architecture, latency budget, and analytics plan.
