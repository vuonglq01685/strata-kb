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


def section_body(text: str, heading: str) -> str | None:
    """Lines after an exact `heading` line, up to the next '# '/'## ' line."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("# "):
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
    """A heading only counts as present outside a fenced code block.
    Without stripping fences first, a BA pasting a reference document (a
    sibling mission, `TEMPLATE.md`, ...) into a ```` ``` ```` block as a
    worked example would satisfy every required heading without the
    document actually containing that section itself — this is the
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
    check, whose error names the offending section."""
    present = {
        line.strip() for line in FENCE_RE.sub("", text).splitlines()
    }
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
    """Body text with all fenced code blocks (mermaid + a fenced kb-context
    block) and any unfenced kb-context block stripped, for inline-citation
    scanning — refs pinned in kb-context are not themselves "citations"."""
    return strip_bare_kb_context(FENCE_RE.sub("", text))


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


def check_context_block(
    text: str, hub: "HubHandle | None"
) -> tuple[list[Issue], KBContext | None]:
    """Parse the kb-context block, resolve its refs at the pinned version,
    and cross-check inline citations against it. Returns the issues and the
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
    issues += check_citation_consistency(text, ctx)
    return issues, ctx
