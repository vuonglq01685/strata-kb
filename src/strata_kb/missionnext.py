"""`kb mission next` engine — which story is done, ready, draft, to-draft or blocked.

Read-only query over every mission plan in a BA repo. Inputs are text,
a dict of DoR counts and a set; `cli.py`'s `kb mission next` reads the files and the
hub. `done` is derived from the hub's `<repo>-svc` history tables (`kb svc
note` rows), never from a status column — a hand-maintained status rots the
moment a ticket merges.

No filesystem, CLI or MCP imports here — the same split `ticketcheck.py`
and `missionlint.py` keep.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from strata_kb import lintcore, mission
from strata_kb.mdmask import _blank_invisible
from strata_kb.mdutils import _SEP_ROW_RE
from strata_kb.svcnote import _ESCAPED_PIPE_SENTINEL, ROW_RE
from strata_kb.ticketcheck import (
    BARE_US_RE,
    SUPERSEDED,
    US_ID_IN_CELL_RE,
    Decision,
    DecisionTable,
    grounded_entries,
    parse_decisions,
)

BACKLOG_HEADING = "## US backlog"

_NONE_WORDS = frozenset({"", "none", "-", "n/a"})

DECIDED = "DECIDED"


@dataclass(frozen=True)
class Story:
    us_id: str
    mission_id: str
    title: str
    depends_on: tuple[str, ...]  # full US ids
    seq_index: int | None  # row index in ## Sequencing; None = absent
    # one reason per unticked `## Open questions` row whose `blocks:` names it
    open_questions: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoryStatus:
    us_id: str
    mission_id: str
    title: str
    status: str  # done | ready | draft | to-draft | blocked
    reasons: tuple[str, ...]  # blocked / draft


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

    questions = _open_question_blocks(text, mid)
    stories: list[Story] = []
    for cells in rows:
        us_id = cells[0]
        if not us_id:
            continue
        title = cells[1] if len(cells) > 1 else ""
        idx, dep_cell = seq.get(us_id, (None, ""))
        oq = tuple(reason for reason, ids in questions if us_id in ids)
        stories.append(Story(us_id, mid, title, dep_ids(dep_cell, mid), idx, oq))

    return mission_id, stories, parse_decisions(text, mission_id or "mission")


_QID_RE = re.compile(r"^(Q\d+)\b")
# Tags end at a spaced dash of any kind (—, –, -, --) or at the row's end.
_OWNER_RE = re.compile(r"\bowner:\s*(.+?)\s*(?:\s(?:—|–|--?)\s|$)", re.I)
# Only the id list right after `blocks:` — never ids later in the row.
_BLOCKS_RE = re.compile(
    r"\bblocks:\s*((?:(?:M-[a-z0-9]+(?:-[a-z0-9]+)*-)?US\d+(?:\s*(?:,|&|\band\b)\s*)?)+)",
    re.I,
)


def _open_question_blocks(text: str, mission_id: str) -> list[tuple[str, set[str]]]:
    """(reason, US ids) per UNTICKED `## Open questions` row with a
    `blocks:` tag. A ticked row is closed and blocks nothing."""
    # blanked view: a row inside a comment or a fence is not a question
    body = lintcore.section_body(
        _blank_invisible(text), lintcore.OPEN_QUESTIONS_HEADING
    )
    out: list[tuple[str, set[str]]] = []
    for line in (body or "").splitlines():
        m = lintcore.CHECKBOX_STATE_RE.match(line.strip())
        if m is None or m.group("mark") != " ":
            continue
        row = m.group("text")
        blocks = _BLOCKS_RE.search(row)
        ids = set(dep_ids(blocks.group(1), mission_id)) if blocks else set()
        if not ids:
            continue
        qid = _QID_RE.match(row)
        owner = _OWNER_RE.search(row)
        label = qid.group(1) if qid else f"open question '{row[:60]}'"
        out.append((f"{label} open (owner: {owner.group(1) if owner else '?'})", ids))
    return out


def grounded_doc(text: str) -> tuple[str | None, str] | None:
    """(repo qualifier, doc id) from the first parseable `- Grounded on:`
    line (the SA writes it in `## Services & order`), or None. The line may
    list several `<repo>:<doc> @ <rev>` entries separated by commas; the
    `-code` entry wins, else the first. The qualifier is None on an
    unqualified entry; `load_from_hub` then resolves the doc by its unique
    holder."""
    for line in text.splitlines():
        entries = grounded_entries(line)
        if not entries:
            continue
        code = next((e for e in entries if e[1].endswith("-code")), entries[0])
        return code[0], code[1]
    return None


def svc_doc_id(doc: str) -> str:
    """The curated `-svc` document paired with a grounded `-code` document:
    `myflix-code` → `myflix-svc`. Derived from the doc, not the repo id —
    a nested federation id (`mid/repo-x`) is a path, not a doc prefix."""
    stem = doc[: -len("-code")] if doc.endswith("-code") else doc
    return f"{stem}-svc"


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


DOR_HEADING = "## Definition of Ready"


def dor_counts(text: str) -> tuple[int, int]:
    """(ticked, total) checkboxes under `## Definition of Ready` of one
    ticket; (0, 0) when the section is absent. Ticking is the BA's act at
    review time, so a fully ticked list is the BA saying "ready for Dev" —
    `statuses` trusts it and does not re-run lint."""
    body = lintcore.section_body(text, DOR_HEADING)
    if body is None:
        return (0, 0)
    marks = [
        m.group("mark")
        for line in body.splitlines()
        if (m := lintcore.CHECKBOX_STATE_RE.match(line.strip()))
    ]
    return (sum(1 for k in marks if k != " "), len(marks))


def _mission_order(stories: list[Story]) -> list[Story]:
    """Sequencing row order first, then stories the table omits, in
    backlog order (stable sort on the 'absent' flag)."""
    return sorted(
        stories,
        key=lambda s: (
            s.seq_index is None,
            s.seq_index if s.seq_index is not None else 0,
        ),
    )


def effective_status(d: Decision, rows: dict[str, Decision]) -> tuple[str, str]:
    """`(status_upper, reason)` of a decision: a `SUPERSEDED` row takes the
    status of the row that `Supersedes` it, down the chain. A cycle or a
    chain with no successor stays `SUPERSEDED`, with the reason saying why."""
    cur, seen = d, {d.id}
    while cur.status.strip().upper() == SUPERSEDED:
        nxt = next((r for r in rows.values() if r.supersedes == cur.id), None)
        if nxt is None:
            return SUPERSEDED, f"{cur.id} SUPERSEDED (no superseding row)"
        if nxt.id in seen:
            return SUPERSEDED, f"supersede cycle {d.id}"
        seen.add(nxt.id)
        cur = nxt
    return (
        cur.status.strip().upper(),
        f"{cur.id} {cur.status.strip() or 'OPEN'} (owner: {cur.owner or '?'})",
    )


def statuses(
    missions: list[ParsedMission],
    drafted: dict[str, tuple[int, int]],
    done: set[str] | None,
    demoted: dict[str, str] | None = None,
) -> list[StoryStatus]:
    """One `StoryStatus` per backlog story, first rule that matches:
    done (id in `done`) → ready (ticket file, every DoR box ticked) → draft
    (ticket file, some box unticked, or no DoR section) → to-draft (no
    file, every dependency done, every D-row blocking it DECIDED) →
    blocked, with one reason per cause. `drafted` maps a ticket id to its
    `dor_counts`. A fully ticked ticket listed in `demoted` (US id →
    reason) reads `draft` with that reason: its parent mission moved on
    after the BA ticked it. `done=None` means the hub could not answer:
    nothing is done, and the caller says why in a note."""
    known = {s.us_id for _m, stories, _d in missions for s in stories}
    done_set = done or set()
    demoted_map = demoted or {}
    out: list[StoryStatus] = []
    for mission_id, stories, decisions in missions:
        # A `Blocks` cell may hold a bare `US<n>` (the same id rule as
        # `Depends on`); resolve it against this mission's id once, not once
        # per story.
        blocking = _blocking(mission_id, decisions)
        for s in _mission_order(stories):
            if s.us_id in done_set:
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "done", ()))
                continue
            if s.us_id in drafted:
                # a ticket whose story the mission still blocks fails lint
                blockers = (
                    *_undecided(s.us_id, blocking, decisions),
                    *s.open_questions,
                )
                if blockers:
                    out.append(
                        StoryStatus(s.us_id, s.mission_id, s.title, "draft", blockers)
                    )
                    continue
                ticked, total = drafted[s.us_id]
                if total and ticked == total:
                    if s.us_id in demoted_map:
                        out.append(
                            StoryStatus(
                                s.us_id,
                                s.mission_id,
                                s.title,
                                "draft",
                                (demoted_map[s.us_id],),
                            )
                        )
                    else:
                        out.append(
                            StoryStatus(s.us_id, s.mission_id, s.title, "ready", ())
                        )
                    continue
                why = (
                    f"DoR {ticked}/{total} ticked"
                    if total
                    else "no Definition of Ready section"
                )
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "draft", (why,)))
                continue
            reasons: list[str] = []
            for dep in s.depends_on:
                if dep in done_set:
                    continue
                reasons.append(
                    f"US {dep} not done" if dep in known else f"US {dep} unknown"
                )
            reasons += _undecided(s.us_id, blocking, decisions)
            reasons += s.open_questions
            status = "blocked" if reasons else "to-draft"
            out.append(
                StoryStatus(s.us_id, s.mission_id, s.title, status, tuple(reasons))
            )
    return out


def _blocking(
    mission_id: str | None, decisions: DecisionTable
) -> list[tuple[Decision, set[str]]]:
    return [
        (d, set(dep_ids(" ".join(d.blocks), mission_id or "")))
        for d in decisions.rows.values()
    ]


def _undecided(
    us_id: str, blocking: list[tuple[Decision, set[str]]], decisions: DecisionTable
) -> list[str]:
    """One reason per D-row that names `us_id` in `Blocks` and is not DECIDED."""
    out: list[str] = []
    for d, blocks in blocking:
        if us_id not in blocks:
            continue
        status, reason = effective_status(d, decisions.rows)
        if status != DECIDED:
            out.append(reason)
    return out


def story_blockers(text: str, us_id: str) -> list[str]:
    """What in the mission `text` still blocks drafting `us_id`: every
    D-row blocking it that is not DECIDED, then every unticked open
    question whose `blocks:` names it. Empty = nothing blocks it."""
    mission_id, stories, decisions = parse_mission(text)
    story = next((s for s in stories if s.us_id == us_id), None)
    if story is None:
        return []
    blocking = _blocking(mission_id, decisions)
    return _undecided(us_id, blocking, decisions) + list(story.open_questions)


def next_story(results: list[StoryStatus]) -> StoryStatus | None:
    return next((r for r in results if r.status == "to-draft"), None)


def _next_line(results: list[StoryStatus]) -> str:
    nxt = next_story(results)
    if nxt is not None:
        return f"Next: {nxt.us_id} — {nxt.title}"
    count = {
        k: sum(1 for r in results if r.status == k)
        for k in ("blocked", "draft", "ready", "done")
    }
    return (
        f"Next: none to draft — {count['blocked']} blocked, {count['draft']} draft, "
        f"{count['ready']} ready, {count['done']} done"
    )


def render(
    results: list[StoryStatus],
    notes: list[str],
    labels: dict[str, str] | None = None,
    unparented: Sequence[StoryStatus] = (),
) -> str:
    """`labels` renames a status in the table only (the `Next:` line still
    keys on the raw status). `unparented` (tickets without a mission) get
    their own block above the `Next:` line (which stays last)."""
    labels = labels or {}
    lines = [f"note: {n}" for n in notes]
    if lines:
        lines.append("")
    lines += ["| US | Mission | Status | Reason |", "|---|---|---|---|"]
    for r in results:
        lines.append(
            f"| {r.us_id} | {r.mission_id} | {labels.get(r.status, r.status)} | "
            f"{'; '.join(r.reasons)} |"
        )
    if unparented:
        lines += ["", "Unparented:"]
        lines += [
            f"- {u.us_id} — {u.title}: {u.status}"
            + (f" ({'; '.join(u.reasons)})" if u.reasons else "")
            for u in unparented
        ]
    lines += ["", _next_line(results)]
    return "\n".join(lines)


def _story_json(r: StoryStatus) -> dict:
    return {**asdict(r), "reasons": list(r.reasons)}


def to_json(
    results: list[StoryStatus],
    notes: list[str],
    unparented: Sequence[StoryStatus] = (),
) -> dict:
    nxt = next_story(results)
    return {
        "notes": list(notes),
        "stories": [_story_json(r) for r in results],
        "unparented": [_story_json(u) for u in unparented],
        "next": nxt.us_id if nxt is not None else None,
    }
