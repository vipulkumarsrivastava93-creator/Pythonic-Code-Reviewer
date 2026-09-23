# Python Code Reviewer — VS Code Extension

Local Pythonic + design code review, right in your editor. Runs the
[`codereview`](https://github.com/vipulkumarsrivastava93-creator/Pythonic-Code-Reviewer)
CLI on save and shows findings in the Problems panel.

## Features

- **Review on save** — static AST detectors run automatically when you save a
  Python file. Findings appear as diagnostics (squiggles + Problems panel)
  with the rule code, severity, and message.
- **Manual review** — `Code Review: Review Current File` command re-runs the
  review on demand.
- **Clear findings** — `Code Review: Clear Findings` removes all diagnostics.
- **LLM review (optional)** — set `codereview.llmOnSave` to `true` to also run
  the local LLM review on save. **Warning:** this is slow (10-30s per file)
  and requires Ollama running locally.

## Requirements

- **Python 3.10+** with the `codereview` CLI installed:
  ```bash
  pip install codereview
  ```
- The CLI must be on your `PATH` (or set `codereview.cliPath` to its location).

## Extension Settings

| Setting | Default | Description |
|---|---|---|
| `codereview.cliPath` | `codereview` | Path to the codereview CLI executable |
| `codereview.reviewOnSave` | `true` | Run the static review on save |
| `codereview.llmOnSave` | `false` | Also run the LLM review on save (slow) |

## How it works

The extension is a thin client over the CLI — it spawns
`codereview --json <file>` as a subprocess, parses the JSON, and maps each
finding to a VS Code `Diagnostic`. No server, no daemon, no code leaves your
machine (unless you enable the LLM path, which talks to local Ollama).

## Development

```bash
cd vscode-extension
npm install
npm run compile   # tsc -> out/
```

Then press F5 in VS Code to launch the Extension Development Host.

## Release

```bash
npm run package   # produces codereview-0.1.0.vsix
```

Install the `.vsix` via the Extensions view → "Install from VSIX...".