"""AC quality — content rules for the DoR lints: what a section *says*,
not only that its heading exists. Started as weasel-phrase detection;
this module is now the one home for every rule that judges content —
placeholders, Given/When/Then coverage, measurable acceptance criteria,
owned unknowns, NFR targets, and review-log rows.

The phrase list mirrors ``docs/ac-quality.md`` scaffolded into BA repos
(source: ``templates/init/ac-quality.md``). Detection is bilingual
(EN + VI) because ticket bodies follow the BA's working language.
Weasel-phrase hits (``weasel_hits``) are reported as WARNINGS only — the
BA judges; a banned phrase alone never flips a DoR verdict. That is a
fact about the weasel list specifically, not a ceiling on this module:
nothing here emits an ``Issue`` or a level itself, so every OTHER rule
(``ac_substance`` included) is free for a caller to wire at whatever
level it chooses, error included.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 'OPEN(<owner>)' marker syntax — requires a non-space first character
# inside the parentheses, so it does not match the empty 'OPEN()'. Kept
# as the marker COUNTER only (ticketlint._unknown_count pairs every
# marker — owned or not — with an Open-questions row: an unowned marker
# is still an unknown that needs a row). Matching this regex says
# nothing about whether the marker's owner is real; OPEN_OWNER_RE /
# owned_open_markers below answer that, and weasel_hits checks ownership
# before muting anything inside a marker's own parentheses.
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
# feeling", it does not grade the outcome. The dotted-path segments
# require 2+ characters each (`[A-Za-z0-9]+`, not `*`) so an abbreviation
# like 'e.g.' — one letter, a dot, one letter — is not mistaken for a
# dotted identifier such as 'user.email'.
MEASURABLE_RE = re.compile(
    r"\d"
    r"|<=|>=|==|[<>]"
    r"|`[^`]+`"
    r"|\b[a-z0-9]+(?:_[a-z0-9]+)+\b"
    r"|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+\b"
    r"|\b[a-z][A-Za-z0-9]+(?:\.[a-z][A-Za-z0-9]+)+\b"
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


# A leading AC id, however the BA actually typed it: 'AC1:', 'AC1 —',
# 'AC1 -', 'AC1.', 'AC1)', a bare 'AC1', case-insensitive ('Ac1'/'ac1'),
# with or without a space before the digits ('AC 1'), with a dotted
# sub-id ('AC1.1'), and wrapped in markdown emphasis or brackets
# ('**AC1**', '[AC1]'). ac_substance strips it before judging:
# MEASURABLE_RE's first alternative is a bare \d, so the id's own digit
# would otherwise count as "measurable" and wave through every AC that
# says nothing else testable — a false negative in a gate, which is the
# failure mode that matters. A gate false positive would be missing a
# form the BA never actually types; a caught reviewer example
# ('**AC1**:') is worth more here than typographic minimalism.
#
# Deliberately does NOT strip a bare numeric list marker ('1. '): unlike
# 'AC<n>', a leading bare number is ambiguous with real content (e.g. a
# measured value opening the sentence), and this repo's templates
# establish the 'AC<n>' convention, not bare numbering — the mandatory
# 'AC' letters keep this regex from ever matching one.
_AC_ID_RE = re.compile(
    r"^\s*[*_\[\s]*AC\s*\d+(?:\.\d+)*[*_\]\s]*[:.)—\-]*\s*",
    re.IGNORECASE,
)


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


def _marker_is_owned(group1: str) -> bool:
    """Whether an ``OPEN(...)``'s captured content names a real owner,
    for ``weasel_hits``'s muting decision specifically.

    A marker may carry a free-text note after the owner —
    ``OPEN(<owner>: <note>)`` — and the note does not change who owns
    the unknown, so only the part before the first ``:`` is checked
    against ``_UNOWNED``: ``OPEN(TBD: alice will decide)`` is still
    unowned. This differs from ``owned_open_markers``, which checks the
    WHOLE captured string and is exercised only against bare markers
    (``OPEN(alice)``, ``OPEN(TBD)``) in its own tests; ``weasel_hits`` is
    the one place a marker routinely carries a note explaining the
    vagueness, so its ownership check needs the split.
    """
    owner = group1.split(":", 1)[0].strip().lower()
    return owner not in _UNOWNED


def weasel_hits(line: str) -> list[str]:
    """Banned phrases in ``line``, matched text verbatim.

    An ``OPEN(<owner>)`` marker suppresses only what sits INSIDE its own
    parentheses, and only when the owner is real: an unowned marker
    (``OPEN(TBD)``, ``OPEN(?)`` — see ``_UNOWNED``) is a placeholder
    wearing the costume of an owner, so it licenses nothing and the text
    inside it stays visible to the weasel check. A marker — owned or
    not — never licenses the rest of the sentence either way. (Before
    0.22.0 a single marker, regardless of ownership, muted the whole
    line — 'Values are configured OPEN(x) and appropriate and a subset
    and responsive.' reported nothing at all.) Weasel-phrase hits are
    reported as WARNINGS only; the AC-level escape hatch in
    ``ac_substance`` is a caller's choice to wire at whatever level it
    wants, error included.
    """
    outside = OPEN_OWNER_RE.sub(
        lambda m: " " if _marker_is_owned(m.group(1)) else m.group(0),
        line,
    )
    hits = [m.group(0) for m in _WEASEL_RE.finditer(outside)]
    if _MEANS_RE.search(outside):
        hits = [h for h in hits if h.lower() not in CONDITIONAL_PHRASES]
    return hits
