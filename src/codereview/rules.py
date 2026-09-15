"""Central rule registry: ids, titles, severities, message templates.

Rule ids follow the pattern <CONCERN><NNN>:
  PY  = Pythonic   (e.g. PY001 "prefer_list_comprehension")
  DES = Design     (e.g. DES001 "large_class")

A rule knows its id, concern/category, default severity, a human title,
a default message and (optionally) a "when NOT to suggest" guard note.
"""

from __future__ import annotations

from dataclasses import dataclass

from codereview.report import Category, Severity


@dataclass(frozen=True)
class Rule:
    code: str                     # e.g. "PY001"
    name: str                     # e.g. "prefer_list_comprehension"
    category: Category            # PYTHONIC or DESIGN
    severity: Severity            # default severity
    title: str                    # short human label
    message: str                  # default wording; detectors may override
    guard: str = ""               # when NOT to suggest (curation, §14)


# ---- Pythonic rules (concern PY) ----
PY001 = Rule("PY001", "prefer_list_comprehension", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer a list comprehension",
             "Use a list comprehension instead of a for-loop with append.",
             guard="Not when the loop body has side effects or is multi-step "
                   "(readability first, §14).")

PY002 = Rule("PY002", "prefer_f_string", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer an f-string",
             "Use an f-string instead of manual concatenation.",
             guard="Not when the concat is 2 short literals done once.")

PY003 = Rule("PY003", "prefer_with_open", Category.PYTHONIC, Severity.SUGGESTION,
             "Use a context manager for the file",
             "Use 'with open(...)' instead of calling open() without closing.")

PY004 = Rule("PY004", "prefer_enumerate", Category.PYTHONIC, Severity.SUGGESTION,
             "Use enumerate",
             "Use enumerate() instead of indexing with range(len(...)).")

PY005 = Rule("PY005", "prefer_zip", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer zip for parallel iteration",
             "Use zip() to iterate two sequences in parallel.")

PY006 = Rule("PY006", "prefer_dict_get", Category.PYTHONIC, Severity.SUGGESTION,
             "Use dict.get",
             "Use dict.get() instead of 'if key in dict' then get.")

PY007 = Rule("PY007", "prefer_identity_vs_equality", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer an identity check",
             "Use 'is' / 'is not' instead of '==' / '!=' when comparing with None.",
             guard="")  # context-free, always a safe suggestion

PY008 = Rule("PY008", "prefer_str_join", Category.PYTHONIC, Severity.SUGGESTION,
             "Use str.join",
             "Use ' '.join(...) instead of string concatenation in a loop.")

PY009 = Rule("PY009", "prefer_defaultdict", Category.PYTHONIC, Severity.SUGGESTION,
             "Use collections.defaultdict",
             "Use a defaultdict/Counter instead of manual init-then-append aggregation.")

PY010 = Rule("PY010", "prefer_any_all", Category.PYTHONIC, Severity.SUGGESTION,
             "Use any()/all()",
             "Use any()/all() instead of a manual loop to test a condition.")

PY011 = Rule("PY011", "prefer_pathlib", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer pathlib.Path",
             "Use pathlib.Path instead of os.path string manipulation.")

PY012 = Rule("PY012", "prefer_dataclass", Category.PYTHONIC, Severity.SUGGESTION,
             "Consider a dataclass",
             "Consider dataclasses.dataclass for a class with mostly attributes.")

PY013 = Rule("PY013", "prefer_key_sorted", Category.PYTHONIC, Severity.SUGGESTION,
             "Use key= with sorted/max/min",
             "Use key= on sorted()/max()/min() instead of manual comparison.")

PY014 = Rule("PY014", "prefer_next_gen", Category.PYTHONIC, Severity.SUGGESTION,
             "Use next() with a generator",
             "Use next(gen, default) instead of a manual first-item loop.")

PY015 = Rule("PY015", "prefer_removeprefix", Category.PYTHONIC, Severity.SUGGESTION,
             "Use str.removeprefix/removesuffix",
             "Use removeprefix()/removesuffix() instead of manual slicing (3.9+).")

PY016 = Rule("PY016", "prefer_top_level_imports", Category.PYTHONIC, Severity.SUGGESTION,
             "Prefer top-level imports",
             "Import inside a function/method body — imports are usually clearer at the "
             "top of the file.",
             guard="Skips deliberate cases: imports under try: (optional deps) and "
                   "imports under if TYPE_CHECKING:.")


# ---- Design rules (concern DES) ----
DES001 = Rule("DES001", "large_class", Category.DESIGN, Severity.INFO,
              "Large class — consider splitting",
              "Class has many lines; consider whether it holds one responsibility.")

DES002 = Rule("DES002", "many_init_params", Category.DESIGN, Severity.WARNING,
              "Too many constructor parameters",
              "__init__ has many parameters; consider a config/dataclass.")

DES003 = Rule("DES003", "duplicated_block", Category.DESIGN, Severity.SUGGESTION,
              "Duplicated code block",
              "This block repeats earlier code. Consider extracting a helper.")

DES004 = Rule("DES004", "duplicated_method", Category.DESIGN, Severity.SUGGESTION,
              "Duplicated method body",
              "Same method body appears in multiple classes. Consider a shared base/mixin.")

DES005 = Rule("DES005", "excessive_nesting", Category.DESIGN, Severity.WARNING,
              "Excessive nesting",
              "Code is nested more than 3 levels deep. Consider extracting a method.",
              guard="Counts only control-flow blocks (for/while/if/with/try/match); "
                    "def and class are scopes, not branches, and are not counted. "
                    "Flags when the block chain reaches 4 or more.")

DES006 = Rule("DES006", "nested_function", Category.DESIGN, Severity.SUGGESTION,
              "Nested function",
              "This function is defined inside another function. Consider hoisting it to "
              "module or method level for readability.",
              guard="Skips idiomatic closures: decorated functions and functions that are "
                    "passed as callbacks/arguments to other calls.")

DES007 = Rule("DES007", "unused_instance_attribute", Category.DESIGN, Severity.SUGGESTION,
              "Unused instance attribute",
              "Instance attribute is assigned in __init__ but never read. Remove it or use it.",
              guard="Skips dataclasses (fields are data), pure data-holder classes (no "
                    "methods to read them), and write-only attributes like caches "
                    "(_cache/_lazy/_memo prefixes).")


RULES: dict[str, Rule] = {r.code: r for r in (
    PY001, PY002, PY003, PY004, PY005, PY006, PY007, PY008, PY009, PY010, PY011, PY012,
    PY013, PY014, PY015, PY016, DES001, DES002, DES003, DES004, DES005, DES006, DES007)}


def get(code: str) -> Rule:
    return RULES[code]