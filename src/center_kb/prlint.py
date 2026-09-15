"""Lint a pull-request description against the required-section canon.

Pure text: no hub access, no git, no network, standard library only — so the
CI job that runs it needs no checkout, no token, and works on fork PRs.

`REQUIRED_SECTIONS` below is the single source of truth for the section list.
The shipped PR template and the `dev-handover` wrappers are pinned against it
in tests/test_templates.py; change it here and those tests tell you what else
has to move.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Literal

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Ticket",
    "kb-context",
    "AC→test map",
    "Placeholder resolutions",
    "Verification",
    "TDD exemptions",
    "Findings",
    "Usage",
)

# The two sections that legitimately have nothing to report. `none` there is
# an explicit answer; everywhere else it is ordinary content.
SENTINEL_SECTIONS: frozenset[str] = frozenset({"TDD exemptions", "Findings"})

# `AC→test map` carries the vocabulary's only non-ASCII character, and a
# hand-typed body will spell it with an ASCII arrow. Accept both; the
# template ships the real arrow.
_HEADING_ALIASES: dict[str, str] = {"AC->test map": "AC→test map"}

# Level 1 and 2 headings both end a section; `###` and deeper are content, so
# a sub-heading inside `## Verification` cannot truncate it. An `# Ticket` h1
# therefore satisfies the requirement too — the content is present and
# visible to a reviewer either way — but the error message below always
# names the `##` form, because that is what the shipped template uses.
_HEADING = re.compile(r"^#{1,2}[ \t]+(?P<name>.+?)[ \t]*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# An unterminated `<!--` is treated as commented through the end of the
# section: it reads as empty and fails, rather than passing on text that
# nobody reviewing the PR can actually see.
_UNTERMINATED_COMMENT = re.compile(r"<!--.*\Z", re.DOTALL)

# There is deliberately no `none` matcher. `none` is ordinary non-empty text,
# so the emptiness check already accepts it in the two sentinel sections, and
# `## Verification` still needs a fence whatever it says. SENTINEL_SECTIONS
# exists to word the error message, not to branch the logic.

# The four exemption classes of `docs/tdd-exemptions.md`, mirrored here so
# `## TDD exemptions` cannot pass on `Exempt: deadline` (reviewer F, H1).
EXEMPTION_SLUGS: frozenset[str] = frozenset({"config", "ci", "docs", "style"})

# One exemption per line, in either the plan's shape
# (`Exempt: config — verified by …`) or a bullet (`- config: …`). The slug
# may be back-ticked; the separator is `:`, `—`, `–` or `-`.
_EXEMPTION_LINE = re.compile(
    r"^(?:-\s*)?(?:Exempt:\s*)?`?(?P<slug>[a-z]+)`?\s*(?::|—|–|-)\s*\S"
)
_NONE = re.compile(r"^none\.?$", re.IGNORECASE)

Level = Literal["error", "warning"]


@dataclass(frozen=True)
class Finding:
    section: str
    code: str
    message: str
    level: Level = "error"


@dataclass(frozen=True)
class PRLintReport:
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "warning")

    @property
    def passed(self) -> bool:
        return not self.errors

    def render(self) -> str:
        if self.passed:
            lines = [
                f"PR description: PASS — all {len(REQUIRED_SECTIONS)} required "
                "sections present and filled."
            ]
        else:
            lines = [f"PR description: FAIL ({len(self.errors)} finding(s))"]
            lines.extend(
                f"  [{f.code}] ## {f.section}: {f.message}" for f in self.errors
            )
        if self.warnings:
            lines.append("warnings:")
            lines.extend(
                f"  [{f.code}] ## {f.section}: {f.message}" for f in self.warnings
            )
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [
                {
                    "section": f.section,
                    "code": f.code,
                    "message": f.message,
                    "level": f.level,
                }
                for f in self.findings
            ],
        }


def _is_fence(line: str) -> str:
    """The fence marker opening/closing on this line, or '' if none."""
    stripped = line.lstrip()
    for marker in ("```", "~~~"):
        if stripped.startswith(marker):
            return marker
    return ""


def _mask_comment_spans(line: str, in_comment: bool) -> tuple[str, bool]:
    """Blank the parts of `line` that sit inside an HTML comment.

    `_split_sections` decides both fence and heading boundaries on this
    masked view, never on the raw line: a fence or a `##` heading that a PR
    reviewer on GitHub would never see, because it sits inside an HTML
    comment, must never count as a real section boundary — a heading hidden
    in a comment leaves its section reading as missing, exactly as if the
    heading weren't there. Comment state persists across lines until a
    `-->` closes it, with no exception for a heading in between: an
    unterminated `<!--` hides everything after it, headings included, which
    swallows the rest of the body the same way an unbalanced fence does —
    including when the unclosed comment sits inside a genuine fence and
    stops that fence from ever closing; that is this same rule applying, not
    a separate case.
    """
    visible: list[str] = []
    i = 0
    while i < len(line):
        if in_comment:
            close = line.find("-->", i)
            if close == -1:
                break
            i = close + len("-->")
            in_comment = False
            continue
        start = line.find("<!--", i)
        if start == -1:
            visible.append(line[i:])
            break
        visible.append(line[i:start])
        i = start + len("<!--")
        in_comment = True
    return "".join(visible), in_comment


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Every heading in the body, paired with the text under it.

    Fenced regions are skipped when looking for headings: a PR that pastes
    markdown into its verification block must not have that paste read as a
    second copy of a required section.

    An unbalanced fence therefore swallows everything after it, and those
    sections report as missing. That is the safe direction: the check goes
    red and the author fixes the fence. It can never turn an unfilled
    description into a passing one.

    Both fence and heading detection run on one comment-masked view of each
    line (`_mask_comment_spans`): a fence or a `##` heading hidden inside an
    HTML comment is invisible to a PR reviewer on GitHub, so it must be
    invisible here too — a commented-out heading is not a section boundary,
    and that section simply reads as missing.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    # A UTF-8 BOM survives `read_text(encoding="utf-8")` as a leading
    # U+FEFF and stops `_HEADING` matching the first line — both the file
    # and the stdin route go through this one function, so stripping it
    # here covers both.
    text = text.lstrip("\ufeff")
    sections: list[tuple[str, list[str]]] = []
    open_fence = ""
    in_comment = False
    for line in text.split("\n"):
        masked, in_comment = _mask_comment_spans(line, in_comment)
        marker = _is_fence(masked)
        if open_fence:
            if marker == open_fence:
                open_fence = ""
            if sections:
                sections[-1][1].append(masked)
            continue
        if marker:
            open_fence = marker
            if sections:
                sections[-1][1].append(masked)
            continue
        match = _HEADING.match(masked)
        if match:
            name = match.group("name").strip()
            sections.append((_HEADING_ALIASES.get(name, name), []))
            continue
        if sections:
            sections[-1][1].append(masked)
    return [(name, "\n".join(lines)) for name, lines in sections]


def _visible(content: str) -> str:
    """The section's content with HTML comments removed."""
    text = _COMMENT.sub("", content)
    text = _UNTERMINATED_COMMENT.sub("", text)
    return text.strip()


def _has_fenced_output(text: str) -> bool:
    """True when a fenced block holds at least one non-blank line."""
    open_fence = ""
    for line in text.split("\n"):
        marker = _is_fence(line)
        if not open_fence:
            if marker:
                open_fence = marker
            continue
        if marker == open_fence:
            open_fence = ""
            continue
        if line.strip():
            return True
    return False


def _exemption_finding(visible: str) -> Finding | None:
    """`none`, or every non-blank line names one of EXEMPTION_SLUGS.

    `_NONE` is checked against the text with markdown emphasis markers
    stripped (`` ` ``, `_`, `*`) so the two sentinel sections keep accepting
    the same "none" spellings (`` `None` ``, `_none_`) the emptiness check
    already tolerated pre-Task-1 (test_none_is_a_valid_answer_...).
    """
    if _NONE.match(visible.strip().strip("`_*")):
        return None
    for line in visible.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _EXEMPTION_LINE.match(stripped)
        if m is None or m["slug"] not in EXEMPTION_SLUGS:
            return Finding(
                "TDD exemptions",
                "unknown-exemption-class",
                f"line {stripped[:60]!r} names no exemption class — each line "
                "is `Exempt: <slug> — verified by <what>` (or `- <slug>: …`) "
                f"with <slug> one of {', '.join(sorted(EXEMPTION_SLUGS))}, or "
                "the whole section reads `none`",
            )
    return None


def lint_body(body: str) -> PRLintReport:
    """Check a PR description against REQUIRED_SECTIONS."""
    found = _split_sections(body)
    counts = Counter(name for name, _ in found)
    first: dict[str, str] = {}
    for name, content in found:
        first.setdefault(name, content)

    findings: list[Finding] = []
    for section in REQUIRED_SECTIONS:
        seen = counts.get(section, 0)
        if seen == 0:
            findings.append(
                Finding(
                    section,
                    "missing-section",
                    f"no '## {section}' heading in the description",
                )
            )
            continue
        if seen > 1:
            findings.append(
                Finding(
                    section,
                    "duplicate-section",
                    f"appears {seen} times; keep exactly one",
                )
            )
        visible = _visible(first[section])
        if not visible:
            hint = (
                " ('none' is a valid answer here)"
                if section in SENTINEL_SECTIONS
                else ""
            )
            findings.append(
                Finding(
                    section,
                    "empty-section",
                    "empty once HTML comments are stripped — fill it in" + hint,
                )
            )
            continue
        if section == "Verification" and not _has_fenced_output(visible):
            findings.append(
                Finding(
                    section,
                    "no-verification-output",
                    "no fenced block holding real output — paste the cmd.test "
                    "and cmd.lint output; a claim is not evidence",
                )
            )
        if section == "TDD exemptions":
            bad = _exemption_finding(visible)
            if bad is not None:
                findings.append(bad)
    return PRLintReport(tuple(findings))
