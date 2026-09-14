# CodeReview Agent — In-Depth Design & Plan

> Status: **Draft — pending review**
> Scope frozen: local-first, Pythonic + Low-Level-Design reviewer, CLI batch v1, JSONL analytics.

---

## 1. Vision & Goal

A local code-review agent for Python that answers the *subjective* question linters cannot:
> *"This code works — but is there a more Pythonic or better-designed way to write it?"*

It deliberately **does not** replace Ruff/Pylint/mypy (deterministic checks). It layers on top of
them to add **judgment**: idiomatic constructs and low-level design judgment.

### Non-goals (v1)
- No IDE plugin (later). v1 is a CLI that accepts a file.
- No real-time watcher (later). v1 is single-shot batch review.
- No hosted LLM in v1. LLM is local-only.
- No raw-code storage in analytics. Analytics records *usage + suggestions*, never code.

---

## 2. High-Level Architecture

```
                        +----------------------------------------+
 user file.py ------>   |  cli.py  (argparse entry, batch mode)   |
                        +--------------------+---------------------+
                                             |
+----------------+          +---------------v-----------------+
|  analytics.ts  |<---------|   agent.py  (orchestrator)      |
|  (JSONL log)   |          |   parse AST -> run detectors    |
+----------------+          |   -> produce Report             |
                            +---------------+-----------------+
                                            |
                     +----------------+----+-----+-----------------+
                     |                |          |                 |
                     |   static      |          |        +---------v----------+
                     |   analyzers   |          |        |  llm/reviewer.py   |
                     |  (pure python)|          |        |  (optional, local) |
                     |  ast-based    |                |   Ollama small model |
                     +----------------+          |   click-to-review mode |
                                                +------------------------+
```

### Two processing paths
1. **Static path (always):** deterministic `ast` detectors. Instant, offline, zero-dependency.
   Catches Pythonic + LLD signals.
2. **LLM path (optional / click-to-review later):** a local small model gives a deeper subjective
   review. Off by default in v1 CLI; gated behind a flag so it never slows the default path.

---

## 3. Responsibilities & Components

| Module | Path | Responsibility |
|---|---|---|
| CLI | `src/codereview/cli.py` | Arg parsing, file loading, formatting the report, `--llm` flag. |
| Orchestrator | `src/codereview/agent.py` | Parse source to AST; run static analyzers; optionally run LLM; merge into one `Report`; emit analytics event. |
| Report model | `src/codereview/report.py` | `Severity`, `Issue`, `Report` dataclasses; dedupe & stats helpers. |
| Shared rules | `src/codereview/rules.py` | Central registry of rule ids (`PY001`, `DES001`...), titles, severities, message templates. |
| Pythonic analyzers | `src/codereview/analyzers/pythonic.py` | AST detectors for idiomatic Python (comprehensions, f-strings, `with`, `enumerate`, ...). |
| Design analyzers | `src/codereview/analyzers/design.py` | AST detectors for LLD (class-size, `__init__` param count, naming, responsibility hints). |
| LLM reviewer | `src/codereview/llm/reviewer.py` | Calls local model (via HTTP to Ollama); turns response into structured `Issue`s. |
| Analytics | `src/codereview/analytics.py` | Appends JSONL events: usage, target kind (function/class/file), suggestions shown. |

---

## 4. Libraries / Dependencies

| Dependency | Role | Why | Introduced when |
|---|---|---|---|
| **stdlib `ast`** | Parse Python source | Built-in, offline, deterministic | v1 |
| **stdlib `argparse`** | CLI args | Built-in entry points without heavy framework | v1 |
| **stdlib `dataclasses`** | value models | Concise, zero-dep data structures | v1 |
| **stdlib `sqlite3`** | **deferred** — airports: not used, JSONL chosen | — | — |
| `jsonschema` | validate analytics events | Optional | later |
| `requests` / http.client | talk to local Ollama | For local LLM call | llm path |
| `pytest` | test runner | dev-only | v1 dev |
| `ruff` | dev lint (our own tool's style) | optional | dev |

> **Decision (confirmed with reviewer):** no DB. Analytics = **JSONL** (append-only JSON logs),
> one file per machine, cheap to parse, works offline. If centralized analytics is needed later,
> a `sync` command can ship only anonymized events.

---

## 5. LLM Responsibility

The LLM is **not** a general "review everything" engine. Its role is narrow and gated:

1. **Trigger:** only on **click-to-review** (later) or `--llm` flag (now). Never on the fast path.
2. **Input:** the relevant AST summary + source lines for a *target* (function/class), *not the whole file*.
   For **LLD** targets specifically, analysis is constrained to **one file at a time** — the user
   designates the design-defining class file (§10), never a directory walk.
3. **Output:** a short list of arrows: `{category, message, confidence, suggestion}` — folded back into
   the `Report` as `Issue`s.
4. **Contract with static analyson:** LLM *authorises* the subjective question; static rules keep
   CLI-fast. LLM adds *design-level* judgement that rules cannot (tools, extensibility).
5. **Privacy:** code is sent only to a local model bound to `localhost`. Default minimum model e.g.
   `llama3/qwen2.5-coder:small`. The local model is optional; if absent, the tool degrades to
   static-only with an explicit banner.

**Prompt design (later)**: slash prompt "Give 2 problematic ARrowed lines, be specific, no code. If code comments
frequent, summarize; prioritize pointer + suggestion not grading.Avoid noise: if nothing actionable, say 'no improvement'."
- **Latency budget (LLM):** target <2s net for one focus (function/class). Running a small model
  locally; the actual value ranges by hardware. If >3s => recommend static-first & defer LLM.

---

## 6. Latency & Performance Budget

| Path | Phase | Target | Notes |
|---|---|---|---|
| Static | load + parse | <50ms for a 1k-line file | `ast.parse` is fast; no deps |
| Static | run detectors | <50ms | single pass, no network |
| Static → total | v1 batch | **<150 ms** | feel instant |
| LLM | prompt build | ~ms | AST/subset only |
| LLM | model inference | **<2s** (warm) | local small model; hardware-bound |
| LLM | parse + merge + print report | ~50ms | polling the local HTTP port |
| Analytics | append JSONL | <1ms | buffered, append-only |

**Design principles:** the assistant-left latency is bound to the *local inference* (LLM).
Static analysis path has tight, near-zero cost and runs unconditionally. Fine.

---

## 7. Analytics Design (JSONL)

Goal: understand **how** the tool is used + which suggestions users see — not what the code is.

### Event schema (`codereview.analytics` emits one JSON object per line)

```jsonc
{
  "ts": "2026-08-28T09:00:00.000Z",
  "event": "review_run",            // review_run | suggestion_action | open
  "session_id": "uuid",
  "mode": "static",                 // static | llm | hybrid
  "target_type": "function",        // function | class | file | module
  "target": "class_name.func",      // only the *name* scope — never code
  "language": "python",
  "lines": 120,                     // numeric counts only
  "issues": [                       // only rule ids + severities
    {"rule": "PY002", "severity": "SUGGESTION"},
    {"rule": "DES001", "severity": "INFO"}
  ],
  "latency_ms": 42,
  "accepted": [0, 1],               // v1: unused placeholder (CLI has no accept)
  "version": "0.1.0"
}
```

### Storage
- Location: `~/.codereview/events/<YYYY-MM-DD>.jsonl`
- Local file, append per event. **Zero code content stored** — never the source.
- Rotation: one file per day; old files can be compacted/exported later.
- **No DB dependency in v1** (matches "cheap/JSON" decision). A `sync`/`export` subcommand can
  later push anonymized JSONL to a dashboard.

### What we learn
1. Which rules/suggestions actually fire (top-N by category).
2. Static vs LLM usage split.
3. What kind of code (function vs class vs file size) the tool sees.
4. (Future) accepted/dismissed rates → tune rule noise.

---

## 8. Security & Privacy Boundaries

- [x] Code analysis stays on-machine; no outbound network by defaults.
- [x] LLM, when used, talks only to a local knockout (default localhost). Optional remote proxy
  requires explicit user enable.
- [x] Analytics stores **no** source; only rule ids, categories, counts, timestamps.
- [x] No secrets/path info in telemetry beyond the target scope name.

---

## 9. Reporting Format

CLI prints a colorized, grouped report:

```
codefile.py — 3 suggestions
┌─ Pythonic
│  PY001  SUGGESTION  Use a list comprehension
│          L10:  result = []
│                for i in items:
│                    result.append(i)
└───────────────────────────────────────
┌─ Design
│  DES002  INFO   Large class (140 lines) — consider splitting
│          L1  class ReportBuilder
└───────────────────────────────────────
```

A `--json` flag dumps the same `Report` as JSON for scripting/CI.

---

## 10. Roadmap / Build Order (with approvals)

**Sequencing decision (confirmed):** cautious approach — **Pythonic first, LLD second.** The
subjective/design layer is the hard one (§13), so we land the Pythonic path end-to-end, learn how
the local-LLM-interpreter behaves, then build LLD on top of the same harness. LLD does **not**
ship with v1.

**LLD analysis constraint (confirmed):** LLD analyzes **one file at a time**, and the user decides
*which* file (the *design-defining* class file), not the tool. Rationale:
- A repo-wide scan overworks the small local model; it loses responsibility/coupling context.
- Strong reviewers review the *backbone* file, not the whole tree.
- Cleaner UX: the tool asks *"which file defines the design?"* → lower noise, higher signal.
- v1 CLI enforces this: LLD analysis requires exactly one explicit file arg (no directory walk).

| # | Milestone | Approx effort | Gate |
|---|---|---|---|
| 0 | **Design doc v1** (this) | — | ✅ you review |
| 1 | Scaffolding: `pyproject.toml`, package dirs, `__init__` | S | ✅ |
| 2 | `report.py` — models + dedupe | S | ✅ |
| 3 | `rules.py` — registry | S | ✅ |
| 4 | `analyzers/pythonic.py` — static Pythonic detectors **(Pythonic phase)** | M | ✅ |
| 5 | `agent.py` — orchestrate + build Report (static path) | M | ✅ |
| 6 | `cli.py` — argparse + display | M | ✅ |
| 7 | `analytics.py` — JSONL events | S | ✅ |
| 8 | `llm/reviewer.py` — local-model adapter (flag-gated); Pythonic-only interpretation | M | later |
| 9 | `tests/test_agent.py` + run pytest | M | ✅ |
| 10 | `analyzers/design.py` — static LLD detectors **(LLD phase)** | M | later |
| 11 | LLD CLI mode enforcing **one-file-at-a-time** | S | later |

**Effort estimate:** core static + CLI + analytics (steps 1–7, 9) land as a working v0.5 quickly —
Pythonic-only. The LLM adapter (8) is a separate increment; LLD (10–11) is gated behind the
Pythonic phase per the cautious order.

---

## 11. Open Questions

1. ~~Should v1 ship the LLM adapter at all?~~ **Decided:** Pythonic phase end-to-end first (static +
   CLI + analytics), LLM adapter and LLD are later increments (see §10).
2. Analytics: do you want an `export`/`summary` subcommand to view counts
   (e.g. `codereview stats`)?
3. FOr LLM, which local runtime do you target — **Ollama** (single binary, easy) vs
   **llama.cpp** / **LM Studio**? Default proposal: Ollama.

---

## 12. Distribution

**Decision (confirmed):** pip-first tool + model-on-demand — the tool ships as a small Python
package, the local model is **fetched at runtime by the user**, never bundled.

### 12.1 The core tension

- Our Python package is a few KB — trivial to distribute via `pip`.
- A bundled local model is hundreds of MB to **GBs** and depends on the user's hardware/VRAM.
- Therefore the model is **never baked into the distributable**. Instead the tool ships a *model
  manager*: detect a local runtime, and guide the user to pull the right small model.

### 12.2 Distribution target

- **Primary:** `PyPI` (package name e.g. `codereview-cli`) — `pip install codereview-cli`.
- **V1 ships static-only core:** zero runtime dependencies, tiny install, works 100% offline.
- The **LLM adapter** (`llm/reviewer.py`) is a thin, optional client tied to a *local* runtime —
  it does not bloat the core package.

### 12.3 Model-on-demand flow

1. User installs the tool: `pip install codereview-cli`.
2. User runs `codereview --llm` on a file.
3. The adapter checks for a local runtime (default target: **Ollama**, or LM Studio).
   - Missing → prints clear onboarding:
     ```
     No local model runtime detected.
     → Install Ollama (https://ollama.com) then:
         ollama pull qwen2.5-coder:1.5b
     ```
   - Present but model not pulled → same message, suggests the exact `ollama pull` command.
4. Handler = `codereview setup` subcommand that automates the checks + prints the exact command.
5. If the user never opts into the LLM, **no model is ever downloaded** — static mode remains the
   90% case and needs nothing beyond pip.

### 12.4 Why this fits the rest of the design

- Keeps the **static analyzer** a tiny, fast, install-and-go tool.
- Makes the local model **opt-in hardware**, not a distribution burden (matches "LLM gated" from §5).
- **Privacy stays intact:** code only ever goes to a local runtime over `localhost` (§8).
- Unbundled model = **no giant releases**; the only thing we publish is code.

### 12.5 What we do / do not bundle

| Bundled in package | Downloaded at runtime (user-host) | Never distributed |
|---|---|---|
| CLI, static analyzers, report, analytics | Small local model (`qwen2.5-coder:1.5b` ~1.5 GB) | Full 7B+ models, GPU toolchains, model weights in pip wheel |

### 12.6 Fallback path

If a user cannot run a local model (no Ollama, no VRAM, company policy), the tool degrades to
**static-only** with an explicit banner: *"LLM unavailable — review limited to deterministic
checks."* This keeps the product useful for everyone.

---

## 13. Positioning & Why-This-Agent-Wins

### 13.1 The observed gap (the thesis)

Extensive usage of generic frontier assistants reveals two concrete weaknesses:

1. **Not Pythonic.** Generic models answer in whatever language the code is; they are not
   *targeted* to any one language. Python's idioms (comprehensions, f-strings, `with`, stdlib
   pattern-matching) are asked only if the user happens to ask — the tool is not *designed* to
   surface them. Our agent is **built around** a Pythonic rubric, so "is there a more Pythonic
   way?" is the default, not an ask.
2. **Weak low-level design.** Frontier models are good at expression-level code but read like a
   *junior* at design time — responsibilities, coupling, abstraction, extensibility. They can write
   a function but don't *measure and reason* about design. That is exactly the layer we target.

**Thesis (what we own):** an agent *anchored to Pythonic idioms with a strict, explicit design
rubric* — and, crucially, **politicked by measurable structural facts** — delivers what generic
frontier "reviewers" miss.

### 13.2 Honest positioning

- **Do not sell "a smarter LLM."** A local small model will be *worse* than GPT-o1 at raw design
  reasoning. Sell **higher signal-to-noise Pythonic + design advice, delivered locally, gated,
  low-noise.**
- **Differentiator = curation + targeting + privacy,** not raw model IQ:
  - a **deterministic rule layer** (structural LLD metrics + Pythonic detectors),
  - a **constrained LLM interpreter** (a rubric-fed prompt that turns measured facts into
    actionable one-liners / proposed designs),
  - **local-run, no code egress** (§8, §12).

### 13.3 Architecture corollary: LLM is the *interpreter*, not the *brain*

- **Deterministic layer finds the signals:** cohesion, responsibility, coupling, large-class, bad
  method structure, non-comprehension loops, string concat, manual file handles, etc. These are
  *facts*, not guesses.
- **LLM interprets + proposes**: takes the measured facts, applies the Pythonic/LLD rubric, and
  articulates *"In this class, X is overloaded; consider Y."* It generalizes and words the
  suggestion — it does not need to *discover* the design issue from memory.
- **Net effect:** our design judgment comes from *structure + rubric*, which the generic models
  lack. Their weakness (junior design) becomes our *strength* because we don't ask the model to do
  design from scratch — we feed it measured structure.

### 13.4 Risk caveats (be honest with ourselves)

- **The capability is a model-quality + curation problem, not a product problem** — this is hard;
  beating frontier LLD effort is a high bar.
- **The "junior on design" weakness is shared by a small local model**, so we must *not* lean on
  the LLM alone for LLD; the deterministic layer carries it.
- **Monetization/Distribution friction** (§12): local model + CLI has adoption friction; the
  strongest product form is the *IDE click-to-review* advisor. CLI is the enabler/MVP, not the end
  goal.

### 13.5 One-line pitch (for the roadmap)

> *"Code works — is there a more Pythonic or better-designed way? Our agent focuses on exactly
> that, with local-first privacy and measured (not guessed) structural design analysis — no code
> leaves your machine."*

---

## 14. Founder/User Taste as a Moat

### 14.1 The thesis

The agent is built by someone who is **both** a domain expert and a power user of the product.
The founder's review experience *is* the rubric — generic LLMs lack taste shaped by real code
reviews; ours is encoded, not incidental.

### 14.2 How taste becomes a product asset

- **"What is Pythonic" is defined by evidence, not opinion.** Before any rule ships, we evaluate
  **multiple code examples and multiple syntax variants** for the same tactic (comprehensions,
  f-strings, `with`, `enumerate`…), compare their readability/obviousness, and only then decide
  what our tool recommends. A "more Pythonic" claim must survive counterexamples (e.g. *"a
  comprehension here hurts readability, don't suggest it"*).
- **Noise-vs-signal judgment becomes explicit rules.** The "don't say X, it's pedantic" knowledge
  a reviewer only gains with time is written down in `rules.py` (§8/§13) as concrete constraints —
  this is the curation that §13 says is the differentiator.
- **LLD intuition** (responsibilities, coupling, "class is doing two jobs") is learned judgment
  the founder owns and feeds into the deterministic design detectors + LLM rubric.

### 14.3 Encoding workflow (before a rule ships)

1. Collect **several real code examples** of the tactic (good, bad, and edge cases).
2. Compare **at least two alternative syntaxes/extractions** for each.
3. Decide a recommendation *and* a "when NOT to suggest" guard.
4. Record both the rule and its counterexample guard in the rules registry.

### 14.4 Risks of founder-as-user (self-awareness)

- **Overfitting to the founder's stack** — the tool drifts toward the idioms/taste of one
  developer's code. Mitigation: the multi-example workflow above + analytics from *others* (§7).
- **Confusing "what I'd prefer" with "what users want"** — UX choices (click-to-review, one-file
  LLD) may feel obvious to the founder but need outside-validation via usage data.
- **Underweighting distribution/onboarding** — the assumed audience ("devs like me") may differ in
  environment. Mitigation: analytics + a fallback path (§12.6).

### 14.5 Bottom line

> The rubric is the product. The founder's taste is the rubric's source — formalized through
> multi-example, multi-syntax evaluation, guardrailed against overfitting, and validated by
> usage analytics.