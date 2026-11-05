"""Layout contract of an L3 unit (rules R1-R9): what the AI structure fix must
leave behind. Pure checks over the unit's markdown plus the PDF context; the
only I/O is reading the chapter files in `lint_doc` and the source in
`source.load_context`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb.l3check import detect, spans
from strata_kb.l3check.source import load_context
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import (
    HEADING_RE,
    is_fallback_id,
    leads_with_number,
    section_map,
)

EVIDENCE_MAX = 80
TAB_WIDTH = 4
DEEP_LIST = 4  # indent beyond the list's first item that makes a code block
MAX_HEADING_LEVEL = 4
MIN_FURNITURE_WORDS = (
    2  # shorter furniture (a page number) is too common inside headings
)

_HEADING = re.compile(r"^(#+)(?:[ \t]+(.*?))?[ \t]*$")
_BACKTICK_FENCE = re.compile(r"^[ \t]*```")
_TILDE_FENCE = re.compile(r"^[ \t]*~~~")
_QUOTE = re.compile(r"^[ \t]*[<>]")
_MD_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
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
    md: bool = False  # Markdown source: R6 allows what Markdown legitimately has


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


def _md_fences(lines: list[str]) -> tuple[list[tuple[int, str]], int | None]:
    """CommonMark fences: (body lines outside any fence, line of an unclosed
    opener). A fence closes on its own character with a run at least as long."""
    out: list[tuple[int, str]] = []
    opener: tuple[str, int, int] | None = None  # (char, run length, line)
    for n, line in enumerate(lines, 1):
        m = _MD_FENCE.match(line)
        if opener is None:
            if m:
                opener = (m.group(1)[0], len(m.group(1)), n)
            else:
                out.append((n, line))
        elif (
            m
            and m.group(1)[0] == opener[0]
            and len(m.group(1)) >= opener[1]
            and not m.group(2).strip()
        ):
            opener = None
    return out, opener[2] if opener else None


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


def _r6(
    lines: list[str], body: list[tuple[int, str]], md: bool
) -> list[tuple[int, str]]:
    if md:
        return []
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


def _only_furniture(words: list[str], furniture: set[tuple[str, ...]]) -> bool:
    """True when `words` is one or more furniture lines back to back."""
    reach = {0}
    for pos in range(len(words)):
        if pos in reach:
            reach |= {
                pos + len(f) for f in furniture if tuple(words[pos : pos + len(f)]) == f
            }
    return bool(words) and len(words) in reach


def _r9(
    body: list[tuple[int, str]], long: set[tuple[str, ...]]
) -> list[tuple[int, str]]:
    """Headings holding text that is not heading text: a link, or a watermark
    or running header (two words or more) docling boxed at the end of the
    title. At least two chunks (id and title) are never furniture, the same
    rule the word check uses to let a draft drop it."""
    bad: list[tuple[int, str]] = []
    for n, line in body:
        m = _HEADING.match(line)
        if m is None or not m.group(2):
            continue
        chunks = m.group(2).split()
        if _URL.search(m.group(2)) or any(
            _only_furniture(detect.normalize_words(" ".join(chunks[keep:])), long)
            for keep in range(2, len(chunks))
        ):
            bad.append((n, line))
    return bad


def _numbered_fallback(body: list[tuple[int, str]]) -> tuple[int, str] | None:
    """(line, text) of the first heading with a made-up id whose title starts
    with a number the PDF gives. Read from the text, so units recorded as
    fallback by an older ingest stop being flagged once that holds."""
    for n, line in body:
        m = _HEADING.match(line)
        parts = (m.group(2) or "").split(maxsplit=1) if m else []
        if len(parts) == 2 and is_fallback_id(*parts) and leads_with_number(parts[1]):
            return n, line
    return None


def _r8(unit_md: str, ctx: UnitContext) -> list[LintIssue]:
    lines = unit_md.splitlines()
    out: list[LintIssue] = []
    cursor = 1
    sid = ctx.span.id
    for f in detect.break_findings(
        spans.section_input(ctx.span, unit_md, ctx.md), ctx.pdf_pages
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
    body, open_fence = _md_fences(lines) if ctx.md else (_body_lines(lines), None)
    found: list[tuple[str, int, str]] = []
    if ctx.is_fallback and (at := _numbered_fallback(body)):
        found.append(("R1", at[0], at[1]))
    found += [("R3", n, t) for n, t in _r3(body)]
    found += [("R4", n, t) for n, t in _r4(body)]
    furniture = {w for f in ctx.furniture if (w := tuple(detect.normalize_words(f)))}
    long = {f for f in furniture if len(f) >= MIN_FURNITURE_WORDS}
    found += [
        ("R5", n, t)
        for n, t in body
        if (words := detect.normalize_words(t))
        and (
            tuple(words) in furniture
            or (not t.lstrip().startswith("|") and _only_furniture(words, long))
        )
    ]
    found += [("R9", n, t) for n, t in _r9(body, long)]
    found += [("R6", n, t) for n, t in _r6(lines, body, ctx.md)]
    if ctx.md:
        if open_fence:
            found.append(("R7", open_fence, lines[open_fence - 1]))
    else:
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


def lint_file(
    raw_md: str, contexts: dict[str, UnitContext], md: bool = False
) -> list[LintIssue]:
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
            md,
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
    md: bool = False,
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
            md,
        )
    issues: list[LintIssue] = []
    for file, contexts in by_file.items():
        raw = kb_dir / doc_id / f"{file}.raw.md"
        if raw.is_file():
            issues += lint_file(raw.read_text(encoding="utf-8"), contexts, md)
    return issues


def load_pdf_context(
    pdf: Path, work_dir: Path, doc_id: str
) -> tuple[dict[int, str], dict[int, list[str]]]:
    """Kept for existing callers: the PDF case of `source.load_context`."""
    return load_context(pdf, work_dir, doc_id, "pdf")
