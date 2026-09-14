"""Lint primitives shared by the BA Definition-of-Ready gates.

`ticketlint.py` (`kb ticket lint`) and `missionlint.py` (`kb mission
lint`) are both thin layers over these checks. No CLI/MCP dependencies
here, and nothing in this module knows the ticket or mission heading
contracts — callers pass their own constants in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from center_kb import kbcontext
from center_kb.doctor import Issue, check_context
from center_kb.kbcontext import KBContext, KBRef

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

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
    re-typing the two `.sub()` calls in the same order."""
    return FENCE_RE.sub("", HTML_COMMENT_RE.sub("", text))


# Inline citation '<doc-id> §<sec>' / '<repo:doc-id> §<sec>' — the
# repo/doc-id groups match kbcontext._REF_RE semantics (repo qualifier
# optional, '§' required). The repo group additionally accepts nested,
# '/'-joined path segments (e.g. 'mid/repo-x') to mirror kbcontext._REF_RE's
# multi-tier federation support — a body citation qualified by a nested
# repo-id must resolve against a kb-context ref pinned at that same nested
# id, not silently drop everything before the last '/'. This mirrors the
# '/'-segment STRUCTURE only, not the exact charset: each segment here is
# `[\w.-]` (Python's `\w` is Unicode-aware by default, so this is wider
# than kbcontext._REF_RE's explicit ASCII-only `[A-Za-z0-9._-]`) — kept as
# it was before this note; not tightened, since narrowing it risks missing
# citations against repo-ids that already validated fine elsewhere. The
# section-id
# group must END on a character that is not sentence punctuation: prose
# that cites a section at the end of a sentence ('... per arinc-424 §5.3.')
# would otherwise absorb the sentence-ending period into the section id,
# making a correctly-pinned citation look unresolved. Unlike the repo/doc-id
# groups, the section id is NOT anchored on its leading character —
# kbcontext._REF_RE's section-id half accepts any non-whitespace token
# ('\S+'), so ids such as '(a' or '_intro' are legal to pin; requiring an
# alnum start here would make this regex fail to match them at all, which
# is worse than the original bug (a missed citation instead of a
# mis-parsed one).
INLINE_CITE_RE = re.compile(
    r"(?:([A-Za-z0-9][\w.-]*(?:/[A-Za-z0-9][\w.-]*)*):)?([A-Za-z0-9][\w.-]*)\s+"
    r"§([^\s,;)\]]*[^\s,;)\].:?!])"
)

# The bare 'kb-context:' key line, at any indent (mirrors kbcontext._KEY_RE)
# — used to strip a kb-context block that was NOT wrapped in a ``` fence.
_KB_CTX_LINE_RE = re.compile(r"^(?P<indent>\s*)kb-context:\s*$")

# Level-1 title: the first non-empty line must start with a single '# '
# (not '## ' — that would be a level-2 heading).
TITLE_RE = re.compile(r"^#\s+\S")


@dataclass
class LintReport:
    """Issues plus notes. A note records a check that could NOT run —
    typically because the caller supplied no filesystem path. Notes never
    affect `passed`: they exist so a skipped check is never mistaken for
    a passed one."""

    issues: list[Issue]
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def to_json(self) -> dict:
        return {
            "pass": self.passed,
            "errors": [i.message for i in self.issues if i.level == "error"],
            "warnings": [i.message for i in self.issues if i.level == "warning"],
            "notes": list(self.notes),
        }

    def render(self) -> str:
        """Mirror `kb doctor`'s output style: one '[error]'/'[warn]'/'[note]'
        line per item, final line 'DoR: PASS' or 'DoR: FAIL'."""
        lines = [
            f"[{'error' if i.level == 'error' else 'warn'}] {i.message}"
            for i in self.issues
        ]
        lines += [f"[note] {note}" for note in self.notes]
        lines.append(f"DoR: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


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

    Deliberately NOT the same view as `visible_body`/`_visible_text`: this
    function blanks FENCES then comments and keeps every line index
    aligned with `text`, for `section_body`'s slicing. `visible_body` and
    `_visible_text` strip COMMENTS then fences and return plain,
    non-index-aligned text, for presence/emptiness/citation scans. Two
    different contracts for two different jobs — see `section_body` for
    why this one must stay index-aligned, and do not merge one into the
    other.
    """

    def _blank(m: re.Match[str]) -> str:
        return "\n" * m.group(0).count("\n")

    return HTML_COMMENT_RE.sub(_blank, FENCE_RE.sub(_blank, text))


def section_body(text: str, heading: str) -> str | None:
    """Lines after an exact `heading` line, up to the next '# '/'## ' line.

    Both the heading search and the terminator search run on
    `_blank_invisible(text)`, so a fenced or commented-out heading never
    opens or closes a section; the returned slice is cut from the
    original lines.
    """
    lines = text.splitlines()
    scan = _blank_invisible(text).splitlines()
    if len(scan) < len(lines):
        # A fence or HTML comment that touches EOF with no trailing
        # newline makes `_blank_invisible`'s pure-'\n' replacement gain a
        # newline the original never had — see its docstring. The
        # shortfall is always exactly one line and always at the end, so
        # padding (not discarding) keeps every earlier index aligned and
        # keeps this document's fence-aware scan intact.
        scan += [""] * (len(lines) - len(scan))
    elif len(scan) > len(lines):  # unreachable; keep the guard
        scan = lines
    start = None
    for i, line in enumerate(scan):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if scan[j].startswith("## ") or scan[j].startswith("# "):
            end = j
            break
    return "\n".join(lines[start:end])


def check_title(text: str) -> list[Issue]:
    for line in text.splitlines():
        if not line.strip():
            continue
        if TITLE_RE.match(line):
            return []
        break
    return [
        Issue(
            "error",
            "missing level-1 title — the first non-empty line must start "
            "with '# '",
        )
    ]


def check_headings(text: str, required: tuple[str, ...]) -> list[Issue]:
    """A heading only counts as present outside a fenced code block or an
    HTML comment. Without stripping fences first, a BA pasting a reference
    document (a sibling mission, `TEMPLATE.md`, ...) into a ```` ``` ````
    block as a worked example would satisfy every required heading without
    the document actually containing that section itself — this is the
    presence-only half of the gate, with no second check to catch it
    (unlike diagrams and citations, which are independently re-verified).
    Mirrors the fence-stripping `citation_scan_text` already does. A
    *single* unpaired fence marker leaves `FENCE_RE` unmatched, so the text
    degrades to the pre-fix, unstripped behaviour rather than erroring — but
    an odd count of 3 or more markers re-pairs across the gap and swallows
    the content between them, reporting headings that are genuinely present
    as missing. That mispairing is not introduced here: `check_diagram` and
    `citation_scan_text` have always shared `FENCE_RE`. The verdict is
    unaffected in practice, because an unpaired fence also fails the diagram
    check, whose error names the offending section. Comments are stripped
    BEFORE fences: a required section wrapped in '<!-- ... -->' (reviewer
    E's G5) is invisible in the rendered document, so it must not count as
    present either — templates ship guidance comments that BAs sometimes
    leave in place instead of replacing with real content."""
    present = {line.strip() for line in _visible_text(text).splitlines()}
    return [
        Issue("error", f"missing required heading: '{heading}'")
        for heading in required
        if heading not in present
    ]


def check_diagram(
    text: str, heading: str, keywords: tuple[str, ...]
) -> list[Issue]:
    r"""The section must carry a ```mermaid fence in which one of `keywords`
    appears at the START OF A LINE.

    Anchoring at line start (rather than requiring the keyword to be the
    fence's very first token) lets a Mermaid init directive
    (`%%{init: ...}%%` on the line above) precede the diagram type, while
    still refusing to match the word 'flowchart' buried in a node label.

    Raises `ValueError` if `keywords` is empty — an empty tuple collapses
    the pattern to `^[ \t]*(?:)\b` (a bare, near-universal line-start
    match), silently turning an error-level gate into a no-op.
    """
    if not keywords:
        raise ValueError("check_diagram: keywords must be non-empty")
    body = section_body(text, heading)
    if body is None:
        return []  # heading missing — already reported by check_headings
    pattern = re.compile(
        r"^[ \t]*(?:" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.M,
    )
    for lang, content in FENCE_RE.findall(body):
        if lang.strip().lower() == "mermaid" and pattern.search(content):
            return []
    joined = " or ".join(f"'{k}'" for k in keywords)
    return [
        Issue(
            "error",
            f"'{heading}' must contain a ```mermaid fence with {joined} "
            "at the start of a line",
        )
    ]


# A '- [ ]' / '- [x]' checkbox list item (open-question rows).
CHECKBOX_ROW_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+)$")

OPEN_QUESTIONS_HEADING = "## Open questions"


def open_question_rows(text: str) -> list[str] | None:
    """Checkbox rows of '## Open questions'; None when the heading is
    absent (callers distinguish 'no section' from 'section with no rows')."""
    body = section_body(text, OPEN_QUESTIONS_HEADING)
    if body is None:
        return None
    return [
        m.group(1)
        for line in body.splitlines()
        if (m := CHECKBOX_ROW_RE.match(line.strip()))
    ]


def check_open_question_owners(rows: list[str]) -> list[Issue]:
    """Warning per open-question row without an 'owner:' tag — an unknown
    without an owner sits until a Dev trips over it (spec NT3)."""
    return [
        Issue(
            "warning",
            f"open question has no 'owner:': '{row.strip()}'",
        )
        for row in rows
        if "owner:" not in row
    ]


def check_recommended_sections(
    text: str, headings: tuple[str, ...]
) -> list[Issue]:
    """Warning per recommended heading that is missing or has an empty
    body. Warning-level on purpose: the required-heading sets are
    compatibility contracts and legacy documents must keep passing."""
    present = {line.strip() for line in _visible_text(text).splitlines()}
    issues: list[Issue] = []
    for heading in headings:
        if heading not in present:
            issues.append(
                Issue(
                    "warning",
                    f"recommended section missing: '{heading}' — add it, "
                    "or write 'N/A — <reason>'",
                )
            )
            continue
        body = section_body(text, heading)
        if body is not None and not visible_body(body):
            issues.append(
                Issue(
                    "warning",
                    f"'{heading}' is empty — fill it or write "
                    "'N/A — <reason>'",
                )
            )
    return issues


REVIEW_RECORD_HEADING = "## Review record"

# The template ships this exact placeholder line; its survival means the
# maturity review never ran.
_REVIEW_PLACEHOLDER = "Not yet reviewed."


def check_review_record(text: str) -> list[Issue]:
    """Warning when the maturity review has not run — '## Review record'
    is missing, still empty, or still holds the template placeholder.
    Warning-level on purpose: the review is an authoring-time aid and the
    BA judges; nothing here may flip a DoR verdict."""
    body = section_body(text, REVIEW_RECORD_HEADING)
    if body is None:
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' missing — the maturity review "
                "has not run (rubric: docs/review-rubric.md)",
            )
        ]
    stripped = HTML_COMMENT_RE.sub("", body)
    if _REVIEW_PLACEHOLDER in stripped:
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' still holds the placeholder "
                f"'{_REVIEW_PLACEHOLDER}' — run the maturity review "
                "(rubric: docs/review-rubric.md)",
            )
        ]
    if not stripped.strip():
        return [
            Issue(
                "warning",
                f"'{REVIEW_RECORD_HEADING}' is empty — run the maturity "
                "review (rubric: docs/review-rubric.md)",
            )
        ]
    return []


def table_rows(body: str) -> list[list[str]]:
    """All '|'-delimited rows of `body` as stripped cell lists. Separator
    rows ('|---|---|') are dropped; the header row is INCLUDED as row 0 —
    callers slice `[1:]` for data rows."""
    _SEP = re.compile(r"^\|[\s:|-]+\|$")
    rows: list[list[str]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        if _SEP.match(line):
            continue
        rows.append([c.strip() for c in line[1:-1].split("|")])
    return rows


def strip_bare_kb_context(text: str) -> str:
    """Drop a 'kb-context:' block that isn't wrapped in a ``` fence."""
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        m = _KB_CTX_LINE_RE.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        indent = len(m.group("indent"))
        i += 1
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            if len(line) - len(line.lstrip()) <= indent:
                break
            i += 1
    return "\n".join(out)


def citation_scan_text(text: str) -> str:
    """Body text with HTML comments, all fenced code blocks (mermaid + a
    fenced kb-context block) and any unfenced kb-context block stripped,
    for inline-citation scanning — refs pinned in kb-context are not
    themselves "citations", and text nobody can see is not a claim."""
    return strip_bare_kb_context(_visible_text(text))


def cite_matches_ref(ref: KBRef, repo: str | None, doc: str, sec: str) -> bool:
    if doc != ref.doc_id or sec != ref.section_id:
        return False
    if repo is None:
        return True  # citation has no repo qualifier — matches any repo
    return repo == ref.repo_id


def check_citation_consistency(text: str, ctx: KBContext) -> list[Issue]:
    scan_text = citation_scan_text(text)
    citations = list(
        dict.fromkeys(
            (m.group(1), m.group(2), m.group(3))
            for m in INLINE_CITE_RE.finditer(scan_text)
        )
    )
    issues: list[Issue] = []
    for repo, doc, sec in citations:
        label = f"{repo}:{doc} §{sec}" if repo else f"{doc} §{sec}"
        if not any(cite_matches_ref(ref, repo, doc, sec) for ref in ctx.refs):
            issues.append(
                Issue(
                    "error",
                    f"citation '{label}' in the body is not in kb-context refs",
                )
            )
    for ref in ctx.refs:
        cited = any(
            cite_matches_ref(ref, repo, doc, sec) for repo, doc, sec in citations
        )
        if not cited:
            issues.append(
                Issue(
                    "warning",
                    f"kb-context ref '{ref}' is never cited in the body",
                )
            )
    return issues


def check_context_tags(ctx: KBContext, hub: "HubHandle") -> list[Issue]:
    """Every tag in the block must be one some document on the federation
    actually publishes. An invented tag makes a ticket look grounded in a
    vocabulary it is not grounded in, and drifts the words used to describe
    KB content away from the words the KB indexes.

    Compared by lowercase key only: `searchdb.py:350` indexes tags as
    `{t.strip().lower() for t in doc.tags}`, so a casing difference has no
    downstream effect and is not worth an edit.

    Not called when the hub is unreachable — without a vocabulary there is
    nothing to conclude, and `check_context_block` already reports the
    unreachable hub as its own error.

    An EMPTY vocabulary gets the same treatment: `federation.iter_entry_dirs`
    yields nothing when `federation/` is missing, and `load_federation`
    silently skips (logging only a warning) any repo whose `index.yaml`
    fails to parse — so an empty vocabulary means the hub mirror is absent
    or unreadable, not that every tag in the block was invented. This
    accepts the same trade-off the `hub is None` branch already accepts: a
    genuinely tagless federation lets a fabricated tag through uncaught.

    A *partially* broken mirror (one corrupt repo among otherwise-healthy
    ones) cannot be distinguished from a real typo at all — the vocabulary
    is simply missing that repo's tags, with no signal left behind to tell
    the two cases apart — so the per-tag error message below names that
    possibility rather than asserting the tag was fabricated.
    """
    from center_kb.federation import load_federation

    vocab = kbcontext.tag_vocabulary(load_federation(hub.federation_dir))
    if not vocab:
        return []
    issues: list[Issue] = []
    for tag in ctx.tags:
        key = tag.strip().lower()
        if key in vocab:
            continue
        cleaned = " ".join(tag.split())
        close = kbcontext.suggest_tags(tag, vocab)
        hint = f" (did you mean {', '.join(close)}?)" if close else ""
        # A near match means this is almost certainly a typo, and correcting
        # the spelling is strictly safer than deleting: it preserves the
        # tag's provenance without touching `refs:` or `version:`. Without a
        # near match there is nothing to correct TO, so deletion is the only
        # remaining option.
        fix = (
            f"correcting the spelling to '{close[0]}' — this looks like a "
            "typo, not a missing tag"
            if close
            else "deleting the tag from the block"
        )
        message = (
            f"kb-context tag '{cleaned}' is not published by any document on "
            f"the hub federation{hint} — list the real ones with `kb tags`."
        )
        if not issues:
            # This caveat is ~300 characters of near-identical prose that
            # would otherwise repeat once per bad tag (Report.render emits
            # one line per issue) — state it once, on the first issue.
            message += (
                " A tag can also be missing because the hub mirror is "
                "incomplete: a repo whose `index.yaml` is unreadable is "
                "silently skipped when the federation is loaded, which "
                "removes that repo's tags from this list."
            )
        message += (
            f" Fix by {fix}; never by re-running `kb context new`, which "
            "would rewrite the pinned version and falsify when the ticket "
            "was grounded"
        )
        issues.append(Issue("error", message))
    return issues


def check_context_block(
    text: str, hub: "HubHandle | None"
) -> tuple[list[Issue], KBContext | None]:
    """Parse the kb-context block, resolve its refs at the pinned version,
    validate its tags against the federation's tag vocabulary, and
    cross-check inline citations against it. Returns the issues and the
    parsed context (None when the block did not parse, in which case the
    ref/citation checks are meaningless and are skipped)."""
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], None

    issues: list[Issue] = []
    if hub is None:
        issues.append(
            Issue(
                "error",
                "hub unreachable — cannot resolve kb-context refs "
                "without a hub",
            )
        )
    else:
        ctx_issues, _results = check_context(text, hub)
        issues += ctx_issues
        issues += check_context_tags(ctx, hub)
    issues += check_citation_consistency(text, ctx)
    return issues, ctx
