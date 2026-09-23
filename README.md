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

### VS Code extension

There's also a **VS Code extension** (`vscode-extension/`) that runs the CLI on save and shows
findings in the Problems panel. See [`vscode-extension/README.md`](vscode-extension/README.md)
for setup and development instructions.

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
| `--llm` | Also run an LLM review (local Ollama by default; see below) |
| `--workers N` | With `--llm`, review up to `N` files in parallel (default 4). Ollama batches concurrent requests on the GPU, so this is nearly free |
| `--setup` | Install the local LLM runtime + model (Ollama + `deepseek-r1:7b` + `nomic-embed-text`), then exit |
| `--yes` | Skip all confirmation prompts (for scripting / CI). Never downloads silently — it still prints what it is doing |
| `--rag-embed` | With `--llm` (or alone — implies it): enable semantic RAG retrieval. Adds sibling-code consistency findings (rule `LLM002`) but costs ~3s to embed the codebase on first run. Off by default (structural RAG only) |

### LLM review (`--llm`)

Pass `--llm` to layer a subjective LLM review on top of the deterministic detectors. The LLM
acts as the *interpreter*: it receives a compact AST summary + source and returns actionable
suggestions (rule id `LLM001`), which are merged into the report and suppressible via
`# noqa: LLM001`.

```bash
codereview --llm path/to/file.py
```

Each file is reviewed through **two lenses**: a *design* focus (class designs, structure) and a
*logic* focus (correctness, edge cases). Findings from both are merged into one report. The two
calls run **concurrently** per file (plus the consistency call when `--rag-embed` is on), so
Ollama's GPU batching processes them together instead of sequentially.

By default it talks to a **local** runtime (Ollama on `localhost:11434`) so code never leaves
your machine. If no runtime is reachable, the tool prints a clear onboarding banner and degrades
to static-only analysis.

To use a remote OpenAI-compatible endpoint instead (Claude, GPT, ...), set the env vars below.

### RAG context (`--rag-embed`)

With `--llm`, the tool builds a **codebase index** (rule `LLM002`) so the model understands each
file's role in the project:

- **Structural (always on):** the AST graph — what each file imports and inherits from. Exact,
  instant, no extra model needed.
- **Semantic (with `--rag-embed`):** embeddings of every class/function, so the model can find
  *sibling* code — other classes doing the same job with the same shape. Embeddings are sent in
  one batched request (~3s for the whole codebase, progress shown).

The index is **disk-cached** to `.codereview/rag-index.json` in the project root (same pattern
as `.mypy_cache/` / `.pytest_cache/`). The cache is keyed by file mtimes — repeat runs load the
index in ~0.1s and skip embedding entirely; any changed file invalidates it and triggers a
rebuild. Delete the folder to force a fresh index.

The cache root is the **nearest project root** (walked up from the reviewed paths to the first
`.git/`, `pyproject.toml`, `setup.py`, `setup.cfg`, or `requirements.txt`), so the cache lands in
the same place regardless of how deep the reviewed paths are — and it travels with the project
when you review someone else's codebase.

The consistency comparison runs as a **separate LLM call** (tagged `LLM002`, suppressible via
`# noqa: LLM002`) so sibling context never corrupts the normal review. It reports only concrete
deviations between a file and its siblings — never generic design advice.

**Pre-check:** before spending ~10s on the consistency call, the tool compares the file's
structural signature (imports + base classes) against its siblings'. If a sibling shares the
exact same signature, the file follows the same pattern — the consistency call is skipped
(returns no findings). This saves ~10s per file on the common case.

After a review with findings, the tool asks if you want to **export** them to
`codereview_findings.txt` (interactive terminals only).

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `CODEREVIEW_EDITOR` | `vscode` | Editor scheme for jump links. `vscode` → `vscode://file/...:line`; `file` → plain `file:///` links |
| `CODEREVIEW_LINKS` | *(on)* | Set to `off` to disable OSC 8 hyperlinks (e.g. terminals that mangle them) |
| `NO_COLOR` | *(off)* | Disable ANSI color output |
| `CODEREVIEW_LLM_URL` | *(local Ollama)* | OpenAI-compatible chat-completions endpoint. Set to use a remote/local override |
| `CODEREVIEW_LLM_API_KEY` | *(none)* | API key for a remote endpoint. If set without a URL, defaults to `https://api.openai.com/v1/chat/completions` |
| `CODEREVIEW_LLM_MODEL` | `deepseek-r1:7b` | Model name sent to the endpoint |

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

## LLM review (on-device by default)

The static analyzers are instant and offline. The `--llm` flag layers a **subjective** review on
top, running **entirely on your machine by default** — never sending code to any online AI
platform unless you explicitly opt in with your own API key.

How it works (see `DESIGN.md`):

- A local runtime such as **Ollama** (or LM Studio) serves the reasoning
  model `deepseek-r1:7b` over `localhost`.
- Code is sent **only** to that local runtime — never to a hosted service.
- The model is **opt-in**: if no local runtime is detected, the tool degrades to static-only
  analysis with a clear banner.
- The model is **fetched by the user at runtime** (`ollama pull ...`), never bundled in the
  package.
- `codereview --setup` automates the whole bootstrap: it installs Ollama (if missing) and pulls
  `deepseek-r1:7b`, asking for explicit confirmation before any download.
- To use a frontier model instead, set `CODEREVIEW_LLM_URL` + `CODEREVIEW_LLM_API_KEY` to any
  OpenAI-compatible endpoint (Claude, GPT, ...).

> **Privacy boundary:** by default no code ever leaves your machine. Remote endpoints are used
> only when you explicitly configure your own API key.

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
  llm/              # local on-device model adapter (Ollama)
    installer.py    # cross-platform Ollama install + model pull (user-confirmed)
    reviewer.py     # OpenAI-compatible client, prompt building, response parsing
    prompts.py      # centralized prompt templates (design/logic focuses)
  rag/              # retrieval-augmented generation (cross-file context)
    chunking.py     # AST -> symbol chunks (Chunk, Chunker)
    embeddings.py   # embedding client + cosine similarity
    index.py        # hybrid index: structural graph + semantic vectors
```

---

## Design notes

- **Local-first & private.** Analysis runs entirely on your machine; no code is sent anywhere by
  default. The LLM path uses a **local on-device model** (`deepseek-r1:7b` via Ollama) bound to
  `localhost` — never an online AI platform unless you opt in with your own API key.
- **Fast.** Static analysis is a single `ast` pass with no network — well under 150 ms for a
  1k-line file. With `--llm`, files are reviewed in parallel (`--workers`), and Ollama batches
  the concurrent requests on the GPU.
- **Zero dependencies.** Everything uses the Python standard library.
- See `DESIGN.md` for the full architecture, latency budget, and analytics plan.
