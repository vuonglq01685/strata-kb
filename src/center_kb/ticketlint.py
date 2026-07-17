"""`kb ticket lint` engine — the Definition-of-Ready gate for BA tickets.

No CLI/MCP dependencies here: `cli.py`'s `kb ticket lint` command and the
`kb_ticket_lint` MCP tool are both thin wrappers over `lint()`. Checks run
in spec §5 order and short-circuit only where continuing would be
meaningless (no parseable kb-context block -> skip the ref-resolution and
citation-consistency checks, 6-8; everything else still runs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from center_kb import kbcontext, ticket
from center_kb.doctor import Issue, check_context
from center_kb.kbcontext import KBContext, KBRef

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

# A fenced code block: ```<lang>\n<content>```. Used both to find mermaid
# diagrams inside a section and to strip fences (mermaid + a fenced
# kb-context block) before scanning prose for inline citations.
_FENCE_RE = re.compile(r"```[ \t]*(\S*)[ \t]*\r?\n(.*?)```", re.S)

# A '- [ ]' / '- [x]' checkbox list item.
_AC_ITEM_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+)$")

# Inline citation '<doc-id> §<sec>' / '<repo:doc-id> §<sec>' — matches
# kbcontext._REF_RE semantics (repo qualifier optional, '§' required).
_INLINE_CITE_RE = re.compile(
    r"(?:([A-Za-z0-9][\w.-]*):)?([A-Za-z0-9][\w.-]*)\s+§([^\s,;)\]]+)"
)

# The bare 'kb-context:' key line, at any indent (mirrors kbcontext._KEY_RE)
# — used to strip a kb-context block that was NOT wrapped in a ``` fence.
_KB_CTX_LINE_RE = re.compile(r"^(?P<indent>\s*)kb-context:\s*$")


@dataclass
class LintReport:
    issues: list[Issue]

    @property
    def passed(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def to_json(self) -> dict:
        return {
            "pass": self.passed,
            "errors": [i.message for i in self.issues if i.level == "error"],
            "warnings": [i.message for i in self.issues if i.level == "warning"],
        }

    def render(self) -> str:
        """Mirror `kb doctor`'s output style: one '[error]'/'[warn]' line per
        issue, final line 'DoR: PASS' or 'DoR: FAIL'."""
        lines = [
            f"[{'error' if i.level == 'error' else 'warn'}] {i.message}"
            for i in self.issues
        ]
        lines.append(f"DoR: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)


def _section_body(text: str, heading: str) -> str | None:
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


def _check_title(text: str) -> list[Issue]:
    for line in text.splitlines():
        if not line.strip():
            continue
        if ticket.TITLE_RE.match(line):
            return []
        break
    return [
        Issue(
            "error",
            "missing level-1 title — the first non-empty line must start "
            "with '# '",
        )
    ]


def _check_headings(text: str) -> list[Issue]:
    present = {line.strip() for line in text.splitlines()}
    return [
        Issue("error", f"missing required heading: '{heading}'")
        for heading in ticket.REQUIRED_HEADINGS
        if heading not in present
    ]


def _check_story(text: str) -> list[Issue]:
    body = _section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by _check_headings
    if not ticket.STORY_RE.search(body):
        return [
            Issue(
                "error",
                "User Story does not match 'As a <role>, I want "
                "<capability>, so that <value>.'",
            )
        ]
    return []


def _check_ac_present(text: str) -> tuple[list[Issue], list[str]]:
    body = _section_body(text, "## Acceptance Criteria")
    if body is None:
        return [], []
    items = [
        m.group(1)
        for line in body.splitlines()
        if (m := _AC_ITEM_RE.match(line.strip()))
    ]
    if not items:
        return [
            Issue(
                "error",
                "Acceptance Criteria must have at least 1 '- [ ]' item",
            )
        ], []
    return [], items


def _check_diagram(text: str, heading: str, keyword: str) -> list[Issue]:
    body = _section_body(text, heading)
    if body is None:
        return []  # heading missing — already reported by _check_headings
    for lang, content in _FENCE_RE.findall(body):
        if lang.strip().lower() == "mermaid" and keyword in content:
            return []
    return [
        Issue(
            "error",
            f"'{heading}' must contain a ```mermaid fence with '{keyword}'",
        )
    ]


def _strip_bare_kb_context(text: str) -> str:
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


def _citation_scan_text(text: str) -> str:
    """Body text with all fenced code blocks (mermaid + a fenced kb-context
    block) and any unfenced kb-context block stripped, for inline-citation
    scanning — refs pinned in kb-context are not themselves "citations"."""
    return _strip_bare_kb_context(_FENCE_RE.sub("", text))


def _cite_matches_ref(ref: KBRef, repo: str | None, doc: str, sec: str) -> bool:
    if doc != ref.doc_id or sec != ref.section_id:
        return False
    if repo is None:
        return True  # citation has no repo qualifier — matches any repo
    return repo == ref.repo_id


def _check_citation_consistency(text: str, ctx: KBContext) -> list[Issue]:
    scan_text = _citation_scan_text(text)
    citations = list(
        dict.fromkeys(
            (m.group(1), m.group(2), m.group(3))
            for m in _INLINE_CITE_RE.finditer(scan_text)
        )
    )
    issues: list[Issue] = []
    for repo, doc, sec in citations:
        label = f"{repo}:{doc} §{sec}" if repo else f"{doc} §{sec}"
        if not any(_cite_matches_ref(ref, repo, doc, sec) for ref in ctx.refs):
            issues.append(
                Issue(
                    "error",
                    f"citation '{label}' in the body is not in kb-context refs",
                )
            )
    for ref in ctx.refs:
        cited = any(
            _cite_matches_ref(ref, repo, doc, sec) for repo, doc, sec in citations
        )
        if not cited:
            issues.append(
                Issue(
                    "warning",
                    f"kb-context ref '{ref}' is never cited in the body",
                )
            )
    return issues


def _check_ac_citations(ac_items: list[str]) -> list[Issue]:
    return [
        Issue(
            "warning",
            f"Acceptance Criterion has no citation: '{item.strip()}'",
        )
        for item in ac_items
        if not _INLINE_CITE_RE.search(item)
    ]


def lint(text: str, hub: "HubHandle | None") -> LintReport:
    issues: list[Issue] = []
    issues += _check_title(text)
    issues += _check_headings(text)
    issues += _check_story(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues

    issues += _check_diagram(text, "## Sequence diagram", "sequenceDiagram")
    issues += _check_diagram(text, "## Business flow", "flowchart")

    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        issues.append(Issue("error", str(exc)))
        ctx = None

    if ctx is not None:
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
        issues += _check_citation_consistency(text, ctx)

    issues += _check_ac_citations(ac_items)

    return LintReport(issues=issues)
