"""Deterministic C2 quality rules shared by kb build, kb summarize and kb approve.

Pure functions only: no I/O, no manifest writes, no LLM. `prose_only()` is
the single unit of measure for every length rule in the pipeline — the
engine's budget and the build gate must never disagree on the denominator.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

from center_kb import models
from center_kb.mdutils import extract_tables, normalize_table

RATIO = 0.35            # L2 prose ≤ RATIO × L3 prose …
FLOOR_CHARS = 120       # … but never required below this many characters
BRIEF_CHARS = 200       # ≤ this much L3 prose: copy verbatim, no LLM
OVERLAP_MIN = 0.45      # share of L2 word-types that occur in the L3 slice
OVERLAP_MIN_WORDS = 20  # overlap is only measured on L2 prose this long
CELLS_PER_SENTENCE = 4  # distinct table cells quoted in one L2 sentence
L1_MAX_WORDS = 25
L0_MAX_WORDS = 30

TABLE_PLACEHOLDER = "[table omitted]"
TABLE_ONLY_LABEL = "Table-only section: {title}."
BRIEF_LABEL = "Brief section: {title}."

_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")


def prose_only(text: str) -> str:
    """Prose lines of an L2/L3 slice: no tables, headings, placeholders,
    figure captions, image refs or HTML comments. Blank runs collapse to
    one; result is stripped. Applied identically to both levels."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        if (
            s.startswith(("|", "#", "<!--", "Figure: "))
            or s == TABLE_PLACEHOLDER
            or _IMAGE_LINE_RE.match(s)
        ):
            continue
        out.append(line.rstrip())
    return "\n".join(out).strip()


def budget(prose_chars: int) -> int:
    return max(FLOOR_CHARS, int(RATIO * prose_chars))


def is_table_only(prose_chars: int) -> bool:
    return prose_chars == 0


def is_brief(prose_chars: int) -> bool:
    return 0 < prose_chars <= BRIEF_CHARS


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Finding:
    code: str
    ref: str
    message: str
    level: Literal["error", "quality"]

    @property
    def text(self) -> str:
        return f"{self.message} (quality)" if self.level == "quality" else self.message


_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9/]{1,7}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_NUMERIC_CELL_STRIP = str.maketrans("", "", ",.%-/")


def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def check_section(
    ref: str, sec: models.SectionEntry, l2_slice: str, l3_slice: str
) -> list[Finding]:
    l2, l3 = prose_only(l2_slice), prose_only(l3_slice)
    n3 = len(l3)
    findings: list[Finding] = []
    findings += _check_length(ref, l2, l3, n3)
    findings += _check_labels(ref, sec, l2, n3)
    findings += _check_l1_words(ref, sec)
    if (is_brief(n3) or is_table_only(n3)) and not findings:
        # Ruling R17: the engine's own deterministic brief/table-only
        # output is a verbatim copy of the L3 prose (or an empty L2 with
        # a fixed label) by construction -- once the length/label check
        # above confirms that, it cannot transcribe a table cell, invent
        # a code, or drift lexically, so running those checks against it
        # can only ever be a false positive.
        return findings
    if l2:
        findings += _check_transcription(ref, l2, l3_slice)
        findings += _check_codes(ref, l2, l3_slice)
        findings += _check_overlap(ref, l2, l3_slice)
    return findings


def _q(code: str, ref: str, msg: str) -> Finding:
    return Finding(code, ref, f"{ref}: {msg}", "quality")


def _check_length(ref: str, l2: str, l3: str, n3: int) -> list[Finding]:
    if n3 > BRIEF_CHARS:
        if not l2:
            return [_q("l2-empty", ref, f"L2 prose is empty while L3 has {n3} chars of prose")]
        limit = budget(n3)
        if len(l2) > limit:
            msg = f"L2 prose {len(l2)} chars > budget {limit} (max({FLOOR_CHARS}, {RATIO:.0%} of {n3}))"
            return [_q("ratio", ref, msg)]
        return []
    if is_brief(n3) and _norm_ws(l2) != _norm_ws(l3):
        return [_q("brief-verbatim", ref, f"brief section ({n3} chars of prose) must carry the L3 prose verbatim in L2")]
    return []


def _check_labels(ref: str, sec: models.SectionEntry, l2: str, n3: int) -> list[Finding]:
    if is_table_only(n3):
        want = TABLE_ONLY_LABEL.format(title=sec.title)
        if sec.summary != want or l2:
            return [_q("table-only-label", ref, f"table-only section must have L1 '{want}' and no L2 prose")]
    elif is_brief(n3):
        want = BRIEF_LABEL.format(title=sec.title)
        if sec.summary != want:
            return [_q("brief-label", ref, f"brief section must have L1 '{want}'")]
    return []


def _check_l1_words(ref: str, sec: models.SectionEntry) -> list[Finding]:
    fixed_labels = (BRIEF_LABEL.format(title=sec.title), TABLE_ONLY_LABEL.format(title=sec.title))
    if sec.summary in fixed_labels:
        return []  # a fixed brief/table-only label never counts toward l1-words
    n = len(sec.summary.split())
    if n > L1_MAX_WORDS:
        return [_q("l1-words", ref, f"L1 summary has {n} words > {L1_MAX_WORDS}")]
    return []


def _table_cells(l3_slice: str) -> set[str]:
    cells: set[str] = set()
    for table in extract_tables(l3_slice):
        for row in normalize_table(table).splitlines():
            for cell in row.split("|"):
                c = cell.strip()
                if len(c) >= 2 and not c.translate(_NUMERIC_CELL_STRIP).isdigit():
                    cells.add(c)
    return cells


def _check_transcription(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    cells = _table_cells(l3_slice)
    if len(cells) < CELLS_PER_SENTENCE:
        return []
    patterns = {c: re.compile(r"(?<!\w)" + re.escape(c) + r"(?!\w)") for c in cells}
    for sentence in _SENTENCE_SPLIT_RE.split(l2):
        hits = [c for c, p in patterns.items() if p.search(sentence)]
        if len(hits) >= CELLS_PER_SENTENCE:
            return [_q("table-transcription", ref,
                       f"L2 sentence quotes {len(hits)} cells of this section's table: '{sentence[:60]}…'")]
    return []


def _check_codes(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    tokens = set(_CODE_RE.findall(l2))
    invented = sorted(t for t in tokens if not re.search(rf"(?<!\w){re.escape(t)}(?!\w)", l3_slice))
    if invented:
        return [_q("invented-code", ref, f"codes in L2 that do not occur in L3: {', '.join(invented)}")]
    return []


def _check_overlap(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    words = _WORD_RE.findall(l2.lower())
    if len(words) < OVERLAP_MIN_WORDS:
        return []
    types = set(words)
    l3_types = set(_WORD_RE.findall(l3_slice.lower()))
    share = len(types & l3_types) / len(types)
    if share < OVERLAP_MIN:
        return [_q("lexical-overlap", ref, f"only {share:.0%} of L2 word-types occur in L3 (< {OVERLAP_MIN:.0%})")]
    return []


def check_doc(entry: models.IndexEntry) -> list[Finding]:
    if not entry.summary.strip():
        return [Finding("l0-empty", entry.id, f"{entry.id}: index.yaml summary is empty", "error")]
    n = len(entry.summary.split())
    if n > L0_MAX_WORDS:
        return [_q("l0-words", entry.id, f"index.yaml summary has {n} words > {L0_MAX_WORDS}")]
    return []
