"""AC quality — content rules for the DoR lints: what a section *says*,
not only that its heading exists. Started as weasel-phrase detection;
this module is now the one home for every rule that judges content —
placeholders, Given/When/Then coverage, measurable acceptance criteria,
owned unknowns, NFR targets, and review-log rows.

The phrase list mirrors ``docs/ac-quality.md`` scaffolded into BA repos
(source: ``templates/init/ac-quality.md``). Detection is bilingual
(EN + VI) because ticket bodies follow the BA's working language.
Callers report hits as WARNINGS only — the BA judges; nothing here may
flip a DoR verdict.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 'OPEN(<owner>)' — an explicitly owned unknown. Its presence anywhere on
# a line suppresses the weasel warning for that line: the vagueness is
# declared and owned, which is the documented exception.
OPEN_RE = re.compile(r"OPEN\([^)\s][^)]*\)")

# Bilingual banned phrases (kept in sync with templates/init/ac-quality.md).
WEASEL_PHRASES: tuple[str, ...] = (
    "configured",
    "đã cấu hình",
    "appropriate",
    "reasonable",
    "phù hợp",
    "hợp lý",
    "a subset",
    "subset",
    "some fields",
    "một tập con",
    "một số trường",
    "responsive",
    "phản hồi tốt",
    "không bị chậm",
    "handled correctly",
    "xử lý đúng",
    "where applicable",
    "if needed",
    "nếu cần",
    "full support for",
    "hỗ trợ đầy đủ",
    "phân biệt theo loại",
    "distinguished by type",
)

# Longest-first so 'a subset' wins over the bare 'subset' fallback and the
# reported phrase is the most specific one. \b guards keep 'configured'
# from firing inside 'preconfigured'. Python's \w is Unicode-aware, so the
# boundaries work for the Vietnamese phrases too.
_WEASEL_RE = re.compile(
    "|".join(
        rf"\b{re.escape(p)}\b"
        for p in sorted(WEASEL_PHRASES, key=len, reverse=True)
    ),
    re.IGNORECASE,
)

# Row 8 of docs/ac-quality.md bans these two phrases only "without the
# means" — when the line already names a distinguishing means, the AC is
# the corrected form the doc prescribes, so the hit is suppressed.
CONDITIONAL_PHRASES: frozenset[str] = frozenset(
    {"distinguished by type", "phân biệt theo loại"}
)

_MEANS_RE = re.compile(
    r"label|nhãn|colou?r|màu|shape|hình dạng|icon|badge|symbol|ký hiệu"
    r"|group|nhóm",
    re.IGNORECASE,
)

# Placeholders: what an unfilled section says. Bilingual, same reason as
# WEASEL_PHRASES. 'N/A' is here because a required section may not answer
# with it — the RECOMMENDED sections that legitimately accept
# 'N/A — <reason>' are checked by check_recommended_sections, not this.
PLACEHOLDER_PHRASES: tuple[str, ...] = (
    "tbd",
    "to be defined",
    "todo",
    "n/a",
    "na",
    "none yet",
    "xxx",
    "chưa rõ",
    "chưa có",
    "chưa xác định",
    "đang cập nhật",
    "cập nhật sau",
)

_PLACEHOLDER_RE = re.compile(
    "|".join(
        rf"\b{re.escape(p)}\b"
        for p in sorted(PLACEHOLDER_PHRASES, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


def is_unfilled(visible: str) -> bool:
    """True when `visible` says nothing: empty, or only placeholder
    phrases and punctuation once they are removed.

    `visible` is what a reader sees — callers pass
    `lintcore.visible_body(body)`, so the templates' guidance comments
    never count as content.
    """
    remainder = _PLACEHOLDER_RE.sub("", visible)
    return not re.sub(r"[\W_]+", "", remainder, flags=re.UNICODE)


# A Given/When/Then triple, in order, in either working language.
GWT_RE = re.compile(
    r"(?:\bgiven\b|\bgiả sử\b|\bcho trước\b)"
    r".*?(?:\bwhen\b|\bkhi\b)"
    r".*?(?:\bthen\b|\bthì\b)",
    re.IGNORECASE | re.DOTALL,
)

# Something a tester can check: a number, a comparison, or an identifier
# naming a real thing (backticked code, snake_case, CamelCase, a dotted
# path). Deliberately generous — this separates "an outcome" from "a
# feeling", it does not grade the outcome.
MEASURABLE_RE = re.compile(
    r"\d"
    r"|<=|>=|==|[<>]"
    r"|`[^`]+`"
    r"|\b[a-z0-9]+(?:_[a-z0-9]+)+\b"
    r"|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b"
    r"|\b[a-z][A-Za-z0-9]*(?:\.[a-z][A-Za-z0-9]*)+\b"
)

# 'OPEN(<owner>)' with the owner captured. OPEN_RE above stays the marker
# COUNTER (ticketlint._unknown_count pairs markers with Open-questions
# rows, and an unowned marker is still an unknown that needs a row); this
# one answers the different question "is the unknown owned".
OPEN_OWNER_RE = re.compile(r"OPEN\(([^)]*)\)")

# An owner that names nobody. 'OPEN(TBD)' is a placeholder wearing the
# costume of an owned unknown — reviewer E's G1 capstone passed on it.
_UNOWNED: frozenset[str] = frozenset(
    {"", "?", "-", "tbd", "todo", "n/a", "na", "chưa rõ", "chưa có"}
)


def owned_open_markers(text: str) -> list[str]:
    """The `OPEN(...)` markers in `text` that name a real owner."""
    return [
        m.group(0)
        for m in OPEN_OWNER_RE.finditer(text)
        if m.group(1).strip().lower() not in _UNOWNED
    ]


# A leading 'AC<n>' id — 'AC1:', 'AC1 —', 'AC1 -', 'AC1.', or a bare
# 'AC1'. ac_substance strips it before judging: MEASURABLE_RE's first
# alternative is a bare \d, so the id's own digit would otherwise count
# as "measurable" and wave through every AC that says nothing else
# testable. A digit inside the AC's own label is not a testable value.
_AC_ID_RE = re.compile(r"^\s*AC\d+\s*[:.—\-]*\s*")


def ac_substance(item: str) -> str | None:
    """None when the AC can be acceptance-tested, else the reason.

    Strips a leading AC id (see `_AC_ID_RE`) before checking, so the id's
    own digit never counts as the AC's measurable value.

    Three ways to pass, in the order a BA would try them: a Given/When/
    Then triple, an owned unknown, or a measurable value. Anything else
    is a sentence about how the system ought to feel.
    """
    body = _AC_ID_RE.sub("", item, count=1)
    if GWT_RE.search(body):
        return None
    if owned_open_markers(body):
        return None
    if MEASURABLE_RE.search(body):
        return None
    return (
        "has no Given/When/Then, no measurable value (a number, a "
        "comparison, or a named identifier) and no owned OPEN(<owner>)"
    )


def nfr_target_ok(cell: str) -> bool:
    """An NFR Target must be a number or an owned unknown — never a mood."""
    return bool(re.search(r"\d", cell)) or bool(owned_open_markers(cell))


@dataclass(frozen=True)
class ReviewRow:
    date: str
    round: int
    business: int
    dev: int
    reviewer: str


def parse_review_row(cells: list[str]) -> "ReviewRow | str":
    """A '| Date | Round | Business | Dev | Reviewer |' row, or the reason
    it is malformed. Scores are 1–5 (docs/review-rubric.md's maturity
    scale); the round is any positive integer — the 3-round cap is a
    warning the caller raises, not a malformed row."""
    if len(cells) != 5:
        return f"has {len(cells)} cells; the table has 5 columns"
    date, round_, business, dev, reviewer = (c.strip() for c in cells)
    if not all((date, round_, business, dev, reviewer)):
        return "has an empty cell; every column must be filled"
    try:
        round_i = int(round_)
    except ValueError:
        return f"Round '{round_}' is not a whole number"
    if round_i < 1:
        return f"Round '{round_}' must be 1 or more"
    scores: list[int] = []
    for name, raw in (("Business", business), ("Dev", dev)):
        try:
            value = int(raw)
        except ValueError:
            return f"{name} score '{raw}' is not a whole number"
        if not 1 <= value <= 5:
            return f"{name} score '{raw}' is outside the 1–5 maturity scale"
        scores.append(value)
    return ReviewRow(date, round_i, scores[0], scores[1], reviewer)


def weasel_hits(line: str) -> list[str]:
    """Banned phrases in ``line``, matched text verbatim.

    An ``OPEN(...)`` marker suppresses only what sits INSIDE its own
    parentheses: declared, owned vagueness is the documented exception,
    and one marker never licenses the rest of the sentence. (Before
    0.22.0 a single marker muted the whole line — 'Values are configured
    OPEN(x) and appropriate and a subset and responsive.' reported
    nothing at all.) The AC-level escape hatch lives at error level in
    ``ac_substance``; these stay warnings.
    """
    outside = OPEN_OWNER_RE.sub(" ", line)
    hits = [m.group(0) for m in _WEASEL_RE.finditer(outside)]
    if _MEANS_RE.search(line):
        hits = [h for h in hits if h.lower() not in CONDITIONAL_PHRASES]
    return hits
