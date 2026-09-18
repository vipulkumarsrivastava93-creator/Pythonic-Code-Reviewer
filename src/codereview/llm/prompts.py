"""Centralized LLM prompts.

All prompt text lives here as constants so it can be refined without touching
the reviewer logic. The prompts are tuned for small local models (7b-class):
they are explicit about what NOT to do, because small models pattern-match
generic advice ("remove unused import", "add type hints") unless forbidden.

Two review focuses are supported:
  - "design": review class designs (responsibilities, coupling, cohesion).
  - "logic": review the logic (bugs, edge cases, correctness, clarity).

Imports/type-hints/docstrings/naming are deliberately out of scope for both —
the static detectors already cover those.

Structure:
  - SYSTEM_PROMPT: the model's role.
  - OUTPUT_CONTRACT: the JSON response schema.
  - FOCUS_PROMPTS: per-focus instructions (design / logic).
  - COMMON_RULES: rules shared by both focuses.
  - USER_PROMPT_TEMPLATE: the per-file review request.
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "You are a senior Python code reviewer with strong opinions about "
    "readability, maintainability, and design. You review code the way an "
    "experienced engineer would in a pull request: you point out concrete, "
    "actionable problems — never generic filler."
)

# Output contract: strict JSON, one sentence per suggestion, no markdown.
OUTPUT_CONTRACT = (
    'Return a JSON object with a single key "suggestions", a list of objects '
    'with keys: line (int), message (string, one sentence, actionable), '
    'severity ("INFO" | "SUGGESTION" | "WARNING").'
)

# Per-focus instructions. Each is a list of bullet points.
FOCUS_PROMPTS: dict[str, list[str]] = {
    "design": [
        "Review the class designs: does each class have one clear "
        "responsibility? Look for coupling, cohesion, and abstraction problems.",
        "For each problem, propose a concrete change: split the class, extract a "
        "mixin or base class, move a responsibility to a more appropriate owner.",
        "Only report design problems that would meaningfully improve the code. "
        "Skip anything cosmetic.",
        "NEVER suggest a refactor unless you can name BOTH the specific problem "
        "AND the specific change. If a function or class is already cohesive, "
        "say nothing.",
        "NEVER say 'move X to a module/class', 'X has multiple responsibilities', "
        "or 'split X into smaller functions' without naming the concrete problem "
        "that motivates it. These are stock refactoring templates, not findings.",
    ],
    "logic": [
        "Review the logic for correctness: bugs, edge cases, error handling, "
        "off-by-one errors, and control-flow clarity.",
        "For each problem, propose a concrete fix: correct the bug, handle the "
        "missing case, simplify the convoluted flow.",
        "Only report logic problems that would change behavior or prevent a real "
        "bug. Skip anything cosmetic.",
    ],
}

# Rules shared by both focuses.
COMMON_RULES = [
    "Only report issues a senior reviewer would actually raise. Be specific: "
    "name the symbol/function/class and say what to change.",
    "NEVER comment on imports, type hints, docstrings, naming, indentation, "
    "or 'be more descriptive'. Only report concrete, code-level problems.",
    "Do NOT repeat issues already found by static analysis.",
    "Only report issues that would meaningfully improve the code. If a finding "
    "is cosmetic or debatable, leave it out.",
    "If nothing is worth reporting, return {\"suggestions\": []}.",
    "Return ONLY the JSON object, no markdown, no commentary.",
]

USER_PROMPT_TEMPLATE = (
    "Review the following Python file.\n"
    "{output_contract}\n"
    "Focus:\n"
    "{focus}\n"
    "Rules:\n"
    "{rules}\n\n"
    "File: {path}\n"
    "AST summary:\n{summary}\n"
    "{static_block}\n\n"
    "Source:\n{source}\n"
)

# Block inserted when static findings exist, so the model knows what is covered.
STATIC_BLOCK_TEMPLATE = (
    "\nAlready reported by static analysis (do NOT repeat these):\n"
    "{findings}"
)

VALID_FOCUSES = ("design", "logic")


def build_user_prompt(
    *,
    path: str,
    summary: str,
    source: str,
    static_issues: list | None = None,
    focus: str = "design",
) -> str:
    """Assemble the user prompt for a single file review.

    `focus` selects which review lens to use: "design" (class designs) or
    "logic" (correctness/edge cases). Defaults to "design".
    """
    if focus not in FOCUS_PROMPTS:
        raise ValueError(f"Unknown focus {focus!r}; expected one of {VALID_FOCUSES}")
    static_block = ""
    if static_issues:
        lines = [f"  {i.code} L{i.line}: {i.message}" for i in static_issues]
        static_block = STATIC_BLOCK_TEMPLATE.format(findings="\n".join(lines))
    focus_lines = "\n".join(f"- {r}" for r in FOCUS_PROMPTS[focus])
    rules = "\n".join(f"- {r}" for r in COMMON_RULES)
    return USER_PROMPT_TEMPLATE.format(
        output_contract=OUTPUT_CONTRACT,
        focus=focus_lines,
        rules=rules,
        path=path,
        summary=summary,
        static_block=static_block,
        source=source,
    )


__all__ = [
    "COMMON_RULES",
    "FOCUS_PROMPTS",
    "OUTPUT_CONTRACT",
    "STATIC_BLOCK_TEMPLATE",
    "SYSTEM_PROMPT",
    "USER_PROMPT_TEMPLATE",
    "VALID_FOCUSES",
    "build_user_prompt",
]