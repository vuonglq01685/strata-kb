"""mdmask — what a reader sees in a Markdown body.

Owns the two invisible layers every Markdown scan must skip: fenced code
blocks (`FENCE_RE`) and HTML comments (`HTML_COMMENT_RE`). `visible_body` and
`_visible_text` strip them; `_blank_invisible` blanks them so line indexes
stay aligned with the original. Comments are always masked before fences.
Imports only `re`, so any module can use it without an import cycle.
"""

from __future__ import annotations

import re

# A fenced code block: ```<lang>\n<content>```. Used both to find mermaid
# diagrams inside a section and to strip fences (mermaid + a fenced
# kb-context block) before scanning prose for inline citations.
FENCE_RE = re.compile(r"```[ \t]*(\S*)[ \t]*\r?\n(.*?)```", re.S)

# An HTML comment — the templates carry guidance in '<!-- ... -->' blocks
# and BAs sometimes leave them in place; scanners that would false-fire on
# guidance text (which mentions 'OPEN(<owner>)' and the banned phrases as
# examples) strip these first.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def visible_body(body: str) -> str:
    """`body` with HTML comments removed, outer whitespace stripped — what
    a reader actually sees. The templates ship guidance in comments, so
    every emptiness judgement runs on this view."""
    return HTML_COMMENT_RE.sub("", body).strip()


def _visible_text(text: str) -> str:
    """`text` with HTML comments and fenced code blocks removed — comments
    FIRST, then fences, because a commented-out region contributes no
    fence, heading, or citation of its own (it isn't rendered, so nothing
    inside it is either). This is the one home for that ordering:
    `check_headings`'s and `check_recommended_sections`'s presence checks
    and `citation_scan_text` all scan this same view rather than each
    re-typing the two `.sub()` calls in the same order. `_blank_invisible`
    below is a different view (it blanks rather than strips, for index
    alignment) but MUST keep the same comments-before-fences order — see
    its own docstring."""
    return FENCE_RE.sub("", HTML_COMMENT_RE.sub("", text))


def _blank_invisible(text: str) -> str:
    """`text` with the CONTENT of every fenced block and every HTML
    comment replaced by blank lines.

    This is a scanning view, never a value handed to a caller: line
    numbers in the blanked copy index the same lines as the original, so
    a scan can decide "does a section end here" while the slice is taken
    from the real text.

    Both layers are blanked for the same reason: neither is visible in
    the rendered document. A '# ' line inside a bash example and a '## '
    heading inside a guidance comment are equally not section
    boundaries. An unpaired fence leaves `FENCE_RE` unmatched and the
    text degrades to its raw form — the same documented limitation
    `check_headings` carries.

    TOTAL NEWLINE COUNT is preserved exactly (each match is replaced by
    the same number of '\\n' characters it contained), but `splitlines()`
    COUNT on the result can be one SHORTER than on `text`: the
    replacement is pure '\\n' characters, so it always ENDS in a newline,
    while the matched span itself may not have (a fence or comment that
    touches EOF with no trailing newline). `str.splitlines()` does not
    count a final, unterminated line the same way once that trailing
    newline appears, so this one case needs the caller to pad rather than
    trust a 1:1 line correspondence — see `section_body`.

    Comments are blanked BEFORE fences — same order, same reason as
    `_visible_text`: a commented-out region contributes no fence of its
    own (it isn't rendered, so a bare ``` a BA left over from the
    template's own '<!-- paste an example like: ``` -->' guidance is not
    one either). Blanking fences FIRST (the pre-fix order) let that
    embedded backtick re-pair with the next REAL fence opener later in
    the document and swallow every heading in between — including the
    section's own — so `section_body` returned None for a heading
    `check_headings` correctly reports as present. This is the one
    respect this function differs from `visible_body`/`_visible_text`:
    this one BLANKS (replaces content with blank lines, keeping every
    line index aligned with `text`, for `section_body`'s slicing) where
    they STRIP (remove the matched span outright, returning plain,
    non-index-aligned text, for presence/emptiness/citation scans) — two
    different contracts for two different jobs, so do not merge one into
    the other, but the comments-before-fences ORDER must stay the same
    invariant in both.
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return FENCE_RE.sub(_blank, HTML_COMMENT_RE.sub(_blank, text))
