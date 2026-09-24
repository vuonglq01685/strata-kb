"""`kb mission next` engine — which story is done, drafted, ready or blocked.

Read-only query over every mission plan in a BA repo (spec
2026-09-24-mission-next-greenfield-design §3). Inputs are text and sets;
`cli.py`'s `kb mission next` reads the files and the hub. `done` is derived
from the hub's `<repo>-svc` history tables (`kb svc note` rows), never from a
status column — a hand-maintained status rots the moment a ticket merges.

No filesystem, CLI or MCP imports here — the same split `ticketcheck.py`
and `missionlint.py` keep.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from strata_kb import lintcore, mission
from strata_kb.mdutils import _SEP_ROW_RE
from strata_kb.svcnote import ROW_RE, _ESCAPED_PIPE_SENTINEL
from strata_kb.ticketcheck import (
    GROUNDED_ON_RE,
    US_ID_IN_CELL_RE,
    DecisionTable,
    parse_decisions,
)

BACKLOG_HEADING = "## US backlog"

# A bare `US<n>` in a `Depends on` cell — not preceded by a word character
# or '-', so the tail of a full `M-x-US2` never re-matches once the full
# ids are blanked out first (see `dep_ids`).
BARE_US_RE = re.compile(r"(?<![\w-])US[1-9]\d*\b")

_NONE_WORDS = frozenset({"", "none", "-", "n/a"})

DECIDED = "DECIDED"


@dataclass(frozen=True)
class Story:
    us_id: str
    mission_id: str
    title: str
    depends_on: tuple[str, ...]   # full US ids
    seq_index: int | None         # row index in ## Sequencing; None = absent


@dataclass(frozen=True)
class StoryStatus:
    us_id: str
    mission_id: str
    title: str
    status: str                   # done | drafted | ready | blocked
    reasons: tuple[str, ...]      # blocked only


ParsedMission = tuple[str | None, list[Story], DecisionTable]


def dep_ids(cell: str, mission_id: str) -> tuple[str, ...]:
    """US ids named in a `Depends on` cell: full ids as written, bare
    `US<n>` prefixed with this mission's id, `none`/`-`/empty → nothing.
    Free text around the ids is ignored."""
    text = cell.strip()
    if text.lower() in _NONE_WORDS:
        return ()
    full = US_ID_IN_CELL_RE.findall(text)
    remaining = US_ID_IN_CELL_RE.sub(" ", text)
    bare = [f"{mission_id}-{m}" for m in BARE_US_RE.findall(remaining)]
    return tuple(dict.fromkeys(full + bare))


def parse_mission(text: str) -> ParsedMission:
    """(mission id, stories in backlog order, decisions) of one mission
    plan. Backlog rows come from the `| US ID | Title |` table via
    `lintcore.table_rows` (row 0 is the header); `## Sequencing` supplies
    `depends_on` and the row index, columns found by header name."""
    m = mission.MISSION_LINE_RE.search(text)
    mission_id = m.group(1) if m else None
    mid = mission_id or ""

    backlog = lintcore.section_body(text, BACKLOG_HEADING)
    rows = lintcore.table_rows(backlog)[1:] if backlog is not None else []

    seq: dict[str, tuple[int, str]] = {}
    seq_body = lintcore.section_body(text, mission.SEQUENCING_HEADING)
    seq_rows = lintcore.table_rows(seq_body) if seq_body is not None else []
    i_id = lintcore.table_column(seq_rows, "us id") if seq_rows else None
    i_dep = lintcore.table_column(seq_rows, "depends on") if seq_rows else None
    if i_id is not None:
        for n, cells in enumerate(seq_rows[1:]):
            if len(cells) <= i_id or not cells[i_id]:
                continue
            dep_cell = cells[i_dep] if i_dep is not None and len(cells) > i_dep else ""
            seq.setdefault(cells[i_id], (n, dep_cell))

    stories: list[Story] = []
    for cells in rows:
        us_id = cells[0]
        if not us_id:
            continue
        title = cells[1] if len(cells) > 1 else ""
        idx, dep_cell = seq.get(us_id, (None, ""))
        stories.append(Story(us_id, mid, title, dep_ids(dep_cell, mid), idx))

    return mission_id, stories, parse_decisions(text, mission_id or "mission")


def grounded_repo_id(text: str) -> str | None:
    """Repo qualifier of the first `- Grounded on: <repo>:<doc> @ <rev>` line
    (the SA writes it in `## Services & order`), or None."""
    for line in text.splitlines():
        m = GROUNDED_ON_RE.match(line.strip())
        if m is not None:
            return m.group("repo")
    return None


def done_ids_from_history(history_l2: str | None) -> set[str]:
    """Ticket ids of every `| Ticket | Title | Domain refs |` row across all
    `hist.*` sections of a `<repo>-svc` history.md (L2). Header and
    separator rows are skipped the way `svcnote._parse_existing_rows`
    skips them. An escaped pipe (`\\|`, written by `escape_cell` when a
    title contains a literal `|`) is swapped for `_ESCAPED_PIPE_SENTINEL`
    before matching, the same way `svcnote._parse_existing_rows` does, so
    `ROW_RE`'s `[^|]` groups don't mistake it for a column delimiter and
    refuse to match the whole row — a merged story with an escaped `|` in
    its title would otherwise silently read as not done."""
    out: set[str] = set()
    for raw in (history_l2 or "").splitlines():
        line = raw.strip()
        if not line.startswith("|") or _SEP_ROW_RE.match(line):
            continue
        m = ROW_RE.match(line.replace("\\|", _ESCAPED_PIPE_SENTINEL))
        if m is None:
            continue
        ticket = m.group("ticket").strip().replace(_ESCAPED_PIPE_SENTINEL, "|")
        if ticket and ticket != "Ticket":
            out.add(ticket)
    return out


def _mission_order(stories: list[Story]) -> list[Story]:
    """Sequencing row order first, then stories the table omits, in
    backlog order (stable sort on the 'absent' flag)."""
    return sorted(
        stories,
        key=lambda s: (s.seq_index is None, s.seq_index if s.seq_index is not None else 0),
    )


def statuses(
    missions: list[ParsedMission], drafted: set[str], done: set[str] | None
) -> list[StoryStatus]:
    """One `StoryStatus` per backlog story, first rule that matches:
    done (id in `done`) → drafted (ticket file exists) → ready (no file,
    every dependency done, every D-row blocking it DECIDED) → blocked,
    with one reason per cause. `done=None` means the hub could not answer:
    nothing is done, and the caller says why in a note."""
    known = {s.us_id for _m, stories, _d in missions for s in stories}
    done_set = done or set()
    out: list[StoryStatus] = []
    for _mission_id, stories, decisions in missions:
        for s in _mission_order(stories):
            if s.us_id in done_set:
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "done", ()))
                continue
            if s.us_id in drafted:
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "drafted", ()))
                continue
            reasons: list[str] = []
            for dep in s.depends_on:
                if dep in done_set:
                    continue
                reasons.append(f"US {dep} not done" if dep in known else f"US {dep} unknown")
            for d in decisions.rows.values():
                if s.us_id in d.blocks and d.status.strip().upper() != DECIDED:
                    reasons.append(f"{d.id} {d.status.strip() or 'OPEN'} (owner: {d.owner or '?'})")
            status = "blocked" if reasons else "ready"
            out.append(StoryStatus(s.us_id, s.mission_id, s.title, status, tuple(reasons)))
    return out


def next_story(results: list[StoryStatus]) -> StoryStatus | None:
    return next((r for r in results if r.status == "ready"), None)


def _next_line(results: list[StoryStatus]) -> str:
    nxt = next_story(results)
    if nxt is not None:
        return f"Next: {nxt.us_id} — {nxt.title}"
    count = {k: sum(1 for r in results if r.status == k) for k in ("blocked", "drafted", "done")}
    return (
        f"Next: none ready — {count['blocked']} blocked, "
        f"{count['drafted']} drafted, {count['done']} done"
    )


def render(results: list[StoryStatus], notes: list[str]) -> str:
    lines = [f"note: {n}" for n in notes]
    if lines:
        lines.append("")
    lines += ["| US | Mission | Status | Reason |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.us_id} | {r.mission_id} | {r.status} | {'; '.join(r.reasons)} |")
    lines += ["", _next_line(results)]
    return "\n".join(lines)


def to_json(results: list[StoryStatus], notes: list[str]) -> dict:
    nxt = next_story(results)
    return {
        "notes": list(notes),
        "stories": [{**asdict(r), "reasons": list(r.reasons)} for r in results],
        "next": nxt.us_id if nxt is not None else None,
    }
