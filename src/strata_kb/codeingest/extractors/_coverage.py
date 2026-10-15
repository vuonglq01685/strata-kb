"""Coverage rows and the `struct.coverage` section.

Structural extractors (routes, pages, jobs, symbols, files, schema) report
how much of the tree they read as `CoverageRow`s on `ExtractResult.coverage`.
`core.run()` merges every row and renders one `struct.coverage` section, so
a reader (or a later ticket-grounding check) can tell "none found" from
"never looked".
"""

from __future__ import annotations

import re

from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.types import CodeSection, CoverageRow

__all__ = [
    "JOBS_DETAIL",
    "NOT_INSTALLED",
    "CoverageRow",
    "merge_rows",
    "render_section",
]

NOT_INSTALLED = "not scanned — install strata-kb[code]"
JOBS_DETAIL = "jobs outside framework schedulers are not detectable"

# Worst first: a higher rank wins when rows for one key disagree.
_STATUS_RANK = {"complete": 0, "partial": 1, "not scanned": 2}
_MAX_SITES = 20  # sites shown in L2 before "+N more"; L3 shows all
_HEADER = "| Area | Scope | Framework/language | Status | Detail |"
_RULE = "| --- | --- | --- | --- | --- |"


_SITE_RE = re.compile(r":\d+$")


def _is_site(detail: str) -> bool:
    return _SITE_RE.search(detail) is not None


def _join_sites(sites: list[str], limit: int | None) -> str:
    # Prose details (`jobs outside ...`, `not scanned ...`) are not sites:
    # they sort first and the cap neither counts nor hides them.
    prose = [s for s in sites if not _is_site(s)]
    located = [s for s in sites if _is_site(s)]
    if limit is not None and len(located) > limit:
        located = [*located[:limit], f"+{len(located) - limit} more"]
    return "; ".join([*prose, *located])


def _sites(detail: str) -> list[str]:
    return [s for s in detail.split("; ") if s]


def merge_rows(rows: list[CoverageRow]) -> list[CoverageRow]:
    """One row per `(area, scope, framework)`, worst status wins. Details
    are de-duplicated and joined with "; ", prose first, then sites, each
    group sorted. Never truncated here:
    L3 shows every site, `render_section` caps only the L2 cell."""
    status: dict[tuple[str, str, str], str] = {}
    sites: dict[tuple[str, str, str], set[str]] = {}
    for row in rows:
        key = (row.area, row.scope, row.framework)
        if key not in status or _STATUS_RANK[row.status] > _STATUS_RANK[status[key]]:
            status[key] = row.status
        sites.setdefault(key, set()).update(_sites(row.detail))
    return [
        CoverageRow(
            *key,
            status[key],
            _join_sites(sorted(sites[key], key=lambda s: (_is_site(s), s)), None),
        )
        for key in sorted(status)
    ]


def _table(rows: list[CoverageRow], limit: int | None) -> list[str]:
    lines = [_HEADER, _RULE]
    for r in rows:
        detail = _join_sites(_sites(r.detail), limit)
        cells = (r.area, r.scope, r.framework, r.status, detail)
        lines.append("| " + " | ".join(escape_cell(c) for c in cells) + " |")
    return lines


def render_section(rows: list[CoverageRow]) -> CodeSection:
    """The `struct.coverage` section. `rows` should come from `merge_rows`;
    they are sorted here again so the output never depends on input order.
    L3 is the same table, untruncated, inside a fence (a bare pipe table in
    L3 would have to echo L2 verbatim)."""
    ordered = sorted(rows, key=lambda r: (r.area, r.scope, r.framework))
    counts = {s: sum(1 for r in ordered if r.status == s) for s in _STATUS_RANK}
    summary = (
        f"Structural coverage: {len(ordered)} rows, {counts['complete']} complete, "
        f"{counts['partial']} partial, {counts['not scanned']} not scanned."
    )
    return CodeSection(
        id="struct.coverage",
        title="Coverage",
        summary=summary,
        group="structure",
        l2_md="\n".join(_table(ordered, _MAX_SITES)) + "\n",
        l3_md="```\n" + "\n".join(_table(ordered, None)) + "\n```\n",
    )
