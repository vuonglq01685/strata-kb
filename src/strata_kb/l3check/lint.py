"""Layout contract of an L3 unit (rules R1-R8): what the AI structure fix must
leave behind. Pure checks over the unit's markdown plus the PDF context; the
only I/O is reading the chapter files in `lint_doc` and the PDF in
`load_pdf_context`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb.ingest import parser, pdftext
from strata_kb.l3check import detect, spans
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import HEADING_RE, section_map

EVIDENCE_MAX = 80
TAB_WIDTH = 4
DEEP_LIST = 4  # indent beyond the list's first item that makes a code block
MAX_HEADING_LEVEL = 4

_HEADING = re.compile(r"^(#+)(?:[ \t]+(.*?))?[ \t]*$")
_BACKTICK_FENCE = re.compile(r"^[ \t]*```")
_TILDE_FENCE = re.compile(r"^[ \t]*~~~")
_QUOTE = re.compile(r"^[ \t]*[<>]")
_LIST_ITEM = re.compile(r"^([ \t]*)(?:[-*+]|\d+[.)])[ \t]+")


@dataclass(frozen=True)
class LintIssue:
    section: str
    rule: str
    line: int  # 1-based within the unit slice
    evidence: str  # <= EVIDENCE_MAX chars


@dataclass(frozen=True)
class UnitContext:
    span: UnitSpan
    is_fallback: bool
    furniture: list[str]  # furniture strings of the span's pages
    pdf_pages: dict[int, str]


def _clip(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EVIDENCE_MAX else one[: EVIDENCE_MAX - 1] + "…"


def _indent(prefix: str) -> int:
    return len(prefix.expandtabs(TAB_WIDTH))


def _body_lines(lines: list[str]) -> list[tuple[int, str]]:
    """(1-based line number, text) of every line outside a ``` fence, fence lines excluded."""
    out: list[tuple[int, str]] = []
    fenced = False
    for n, line in enumerate(lines, 1):
        if _BACKTICK_FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            out.append((n, line))
    return out


def _r3(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    previous = 2  # the unit's own `## ` line
    for n, line in body:
        m = _HEADING.match(line)
        if m is None or n == 1:
            continue
        level = len(m.group(1))
        if level == 1:
            bad.append((n, line))
            continue
        if not m.group(2) or level > MAX_HEADING_LEVEL or level - previous > 1:
            bad.append((n, line))
        previous = level
    return bad


def _prose_blocks(body: list[tuple[int, str]]) -> list[tuple[int, list[str]]]:
    """(first line number, normalized words) of each blank-separated prose block."""
    blocks: list[tuple[int, list[str]]] = []
    current: list[tuple[int, str]] = []

    def flush() -> None:
        if current:
            words = detect.normalize_words(" ".join(t for _, t in current))
            blocks.append((current[0][0], words))
            current.clear()

    for n, line in body:
        if detect._NON_PROSE.match(line):
            flush()
        elif line.strip():
            current.append((n, line.strip()))
        else:
            flush()
    flush()
    return blocks


def _r4(body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    seen: set[tuple[str, ...]] = set()
    bad: list[tuple[int, str]] = []
    lines = dict(body)
    for n, words in _prose_blocks(body):
        if len(words) < detect.MIN_RUN:
            continue
        key = tuple(words)
        if key in seen:
            bad.append((n, lines[n]))
        seen.add(key)
    return bad


def _r6(lines: list[str], body: list[tuple[int, str]]) -> list[tuple[int, str]]:
    bad = [(n, line) for n, line in body if _QUOTE.match(line)]
    bad += [(n, ln) for n, ln in enumerate(lines, 1) if _TILDE_FENCE.match(ln)]
    base: int | None = None
    for n, line in body:
        item = _LIST_ITEM.match(line)
        if item:
            depth = _indent(item.group(1))
            if base is None:
                base = depth
            elif depth - base >= DEEP_LIST:
                bad.append((n, line))
        elif line.strip() and base is not None:
            if _indent(line[: len(line) - len(line.lstrip())]) <= base:
                base = None
    return sorted(set(bad))


def _r8(unit_md: str, ctx: UnitContext) -> list[LintIssue]:
    lines = unit_md.splitlines()
    out: list[LintIssue] = []
    cursor = 1
    sid = ctx.span.id
    for f in detect.break_findings(
        spans.section_input(ctx.span, unit_md), ctx.pdf_pages
    ):
        head = " ".join(f.evidence.get("next", "").split()[:3])
        at = next(
            (n for n in range(cursor, len(lines) + 1) if head and head in lines[n - 1]),
            1,
        )
        cursor = at + 1
        out.append(LintIssue(sid, "R8", at, _clip(f.evidence.get("l3", ""))))
    return out


def lint_unit(unit_md: str, ctx: UnitContext) -> list[LintIssue]:
    """Issues of one unit (`unit_md` starts at its `## ` line), by rule then line."""
    sid = ctx.span.id
    lines = unit_md.splitlines()
    body = _body_lines(lines)
    found: list[tuple[str, int, str]] = []
    if ctx.is_fallback:
        found.append(("R1", 1, lines[0] if lines else ""))
    found += [("R3", n, t) for n, t in _r3(body)]
    found += [("R4", n, t) for n, t in _r4(body)]
    furniture = {w for f in ctx.furniture if (w := tuple(detect.normalize_words(f)))}
    found += [
        ("R5", n, t) for n, t in body if tuple(detect.normalize_words(t)) in furniture
    ]
    found += [("R6", n, t) for n, t in _r6(lines, body)]
    fences = [n for n, t in enumerate(lines, 1) if _BACKTICK_FENCE.match(t)]
    if len(fences) % 2:
        found.append(("R7", fences[-1], lines[fences[-1] - 1]))
    issues = [LintIssue(sid, r, n, _clip(t)) for r, n, t in found]
    issues += _r8(unit_md, ctx)
    return sorted(issues, key=lambda i: (i.rule, i.line))


def _orphans(raw_md: str) -> list[LintIssue]:
    """One R6 issue per run of text outside any `## <id>` unit: before the first
    heading, or under a `## ` line HEADING_RE rejects (section_map drops both)."""
    out: list[LintIssue] = []
    owner, inside, flagged = "", False, False
    for n, line in enumerate(raw_md.splitlines(), 1):
        if line.startswith("## "):
            m = HEADING_RE.match(line)
            inside, flagged = m is not None, False
            owner = m.group("sid") if m else owner
        if inside or not line.strip() or flagged:
            continue
        flagged = True
        out.append(LintIssue(owner, "R6", n, _clip(f"text outside a ## unit: {line}")))
    return out


def lint_file(raw_md: str, contexts: dict[str, UnitContext]) -> list[LintIssue]:
    """Lint every `## ` unit of a chapter file (or a draft) plus R2 and orphan
    text across it. A unit whose id has no context gets a neutral one (no PDF
    checks): the PDF-free rules still apply."""
    issues = _orphans(raw_md)
    for sid, slices in section_map(raw_md).items():
        if len(slices) > 1:
            issues.append(LintIssue(sid, "R2", 1, _clip(slices[1].splitlines()[0])))
        ctx = contexts.get(sid) or UnitContext(
            UnitSpan(id=sid, file="", chapter="", page=None, end_page=None),
            False,
            [],
            {},
        )
        for unit in slices:
            issues += lint_unit(unit, ctx)
    return issues


def lint_doc(
    kb_dir: Path,
    doc_id: str,
    data: SpansFile,
    pdf_pages: dict[int, str],
    furniture: dict[int, list[str]],
) -> list[LintIssue]:
    """Lint each chapter file that holds units of `data`."""
    by_file: dict[str, dict[str, UnitContext]] = {}
    for span in data.units:
        pages = range(span.page, (span.end_page or span.page) + 1) if span.page else []
        by_file.setdefault(span.file, {})[span.id] = UnitContext(
            span,
            span.id in data.fallback_units,
            [text for p in pages for text in furniture.get(p, [])],
            pdf_pages,
        )
    issues: list[LintIssue] = []
    for file, contexts in by_file.items():
        raw = kb_dir / doc_id / f"{file}.raw.md"
        if raw.is_file():
            issues += lint_file(raw.read_text(encoding="utf-8"), contexts)
    return issues


def load_pdf_context(
    pdf: Path, work_dir: Path, doc_id: str
) -> tuple[dict[int, str], dict[int, list[str]]]:
    """(text layer per page, furniture per page) of the source PDF."""
    return pdftext.page_texts(pdf), parser.furniture_by_page(
        parser.load_or_parse(pdf, work_dir / doc_id)
    )
