"""The one shared L2 Markdown-table-cell escaper (task review, Important 3).

**Why this module exists.** `api.py`, `commands.py`, `deps.py`,
`integrations.py`, `schema.py`, and `services.py` each kept their own
byte-identical `_escape_pipe(text) -> text.replace("|", "\\|")` — six
copies of a rule that only ever implemented half of it. A literal `|`
inside a cell is not the only character that breaks an L2 table: an
embedded newline does too, just as surely, by starting a new Markdown
table row (or ending the table outright) in the middle of what is
supposed to be one cell. A YAML literal-block `summary:` value, or an npm
script body with a `\n` in it, reproduces this — the row visibly
truncates and the remainder escapes the table into surrounding prose. A
worse tail risk: if the escaped-out text happens to produce two
consecutive lines that both start with `|`, the L3 fenced block that
follows can pick up what looks like a genuine Markdown table that is not
verbatim in L2, which fails `kb build`'s L2/L3 verbatim-echo check.

**The fix.** `escape_cell` first collapses *all* whitespace runs (spaces,
tabs, newlines alike) to a single space via `" ".join(text.split())` —
the same idiom `schema.py`'s `_clean_type` already uses for exactly this
reason — and only then escapes a literal `|`. Collapsing before escaping
means a `|` that whitespace-splitting exposed (none — `split()` never
touches `|`) is moot; the two steps do not interact, but the order
matches every other cleaner in this codebase that collapses whitespace
first.

Every one of the six modules above imports `escape_cell` from here rather
than keeping its own copy, for the same "fix it once" reason
`_envkeys.py` is the one place `sanitize_env_key`/`redact_userinfo` live.
"""
from __future__ import annotations


def escape_cell(text: str) -> str:
    """Make `text` safe as one L2 Markdown table cell: collapse every
    run of whitespace (including an embedded newline) to a single space,
    then escape a literal `|` so it can never read as an extra column
    delimiter or, via a newline, split the cell into what looks like
    extra table rows."""
    return " ".join(text.split()).replace("|", "\\|")
