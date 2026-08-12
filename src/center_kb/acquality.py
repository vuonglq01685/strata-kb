"""AC quality — banned weasel-phrase detection for the DoR lints.

The phrase list mirrors ``docs/ac-quality.md`` scaffolded into BA repos
(source: ``templates/init/ac-quality.md``). Detection is bilingual
(EN + VI) because ticket bodies follow the BA's working language.
Callers report hits as WARNINGS only — the BA judges; nothing here may
flip a DoR verdict.
"""

from __future__ import annotations

import re

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


def weasel_hits(line: str) -> list[str]:
    """Banned phrases in ``line``; ``[]`` when an ``OPEN(...)`` suppressor
    is present. Returns the matched text verbatim (original casing).

    The two row-8 phrases in ``CONDITIONAL_PHRASES`` are only banned
    "without the means" — a hit is dropped when the line already names a
    distinguishing means (label, color, shape, icon, badge, symbol, group).
    """
    if OPEN_RE.search(line):
        return []
    hits = [m.group(0) for m in _WEASEL_RE.finditer(line)]
    if _MEANS_RE.search(line):
        hits = [h for h in hits if h.lower() not in CONDITIONAL_PHRASES]
    return hits
