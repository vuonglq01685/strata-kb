# `kb mission next` — PR 1 (BA engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only `kb mission next` that tells a BA which story is done, drafted, ready or blocked across every mission in `missions/`, deriving "done" from the hub's `<repo>-svc` history tables.

**Architecture:** One pure engine module `missionnext.py` (text in, statuses out) reusing the existing mission/decision/table parsers; one thin `cli.py` command that reads files and the hub and calls it. `ticketcheck.Decision` grows a `blocks` field; `_table_column` moves to `lintcore.table_column` so both engines share it.

**Tech Stack:** Python 3.12, typer CLI, pytest, existing `lintcore` / `mission` / `ticketcheck` / `svcnote` helpers.

**Spec:** `docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md` — §3 (engine and CLI), §6 (tests), §7 PR 1. This plan covers PR 1 only; PR 2 (BA skills/templates) and PR 3 (Dev side) get their own plans.

## Global Constraints

- No version bump in `pyproject.toml` or `uv.lock`; CHANGELOG entry under `## Unreleased`.
- `mdutils.py` is frozen — import from it, never edit it.
- `check_backlog` (missionlint) is HIGH impact (feeds `mission_lint` and `ticket_lint`) — this PR does **not** touch it. Deviation from spec §3.2 recorded in Task 6: the backlog is read with `lintcore.table_rows`, no `parse_backlog` extraction.
- Engine module has no filesystem, CLI or MCP imports (same split as `ticketcheck.py` / `missionlint.py`).
- `kb mission next` exits 0 after a report; only a usage error (missing `--missions-dir` / `--tickets-dir` path) exits 1 with a red line, mirroring `kb ticket check`.
- Every test runs in the foreground (`pytest … -q`); never `run_in_background`.
- Commit per task with `git add <explicit paths>`; never `git add -A` / `git commit -a`. Commit messages via `git commit -F <file>` written to the session scratchpad (PowerShell here-strings through the Bash tool commit a `@` subject).
- Before the final commit of the PR, run `mcp__gitnexus__detect_changes({scope: "all"})` and report it (project rule).
- Test commands: `uv run pytest tests/<file> -q` from the repo root. Lint: `uv run ruff check src tests`.

---

### Task 1: `lintcore.table_column` and `Decision.blocks`

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/lintcore.py` (after `table_rows`, ~line 621)
- Modify: `src/strata_kb/ticketcheck.py:90-125` (`Decision`, `parse_decisions`) and `:491-493` (`_table_column`)
- Test: `tests/test_ticketcheck.py` (append)

**Interfaces:**
- Consumes: `lintcore.table_rows(body) -> list[list[str]]` (header row included as row 0).
- Produces:
  - `lintcore.table_column(rows: list[list[str]], name: str) -> int | None` — index of the header cell equal to `name` (case-insensitive, stripped), `None` when absent or `rows` empty.
  - `ticketcheck.Decision(id: str, status: str, owner: str, blocks: tuple[str, ...] = ())` — frozen dataclass; `blocks` holds every US id found in the `Blocks` cell (full `M-<slug>-US<n>` ids as written; bare `US<n>` prefixed with the mission id from the row's own file is **not** done here — `parse_decisions` has no mission id; it keeps raw tokens, see below).
  - `ticketcheck.US_ID_IN_CELL_RE = re.compile(r"\bM-[a-z0-9]+(?:-[a-z0-9]+)*-US[1-9]\d*\b")` — module constant reused by Task 2.
  - `ticketcheck.parse_decisions(text, source) -> DecisionTable` unchanged signature; each `Decision.blocks` = tuple of `US_ID_IN_CELL_RE` matches in the `Blocks` column (deduplicated, in order); empty when the column is absent.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ticketcheck.py`:

```python
# --- Task 1 (mission next PR 1): Decision.blocks, lintcore.table_column ----


def test_table_column_is_shared_from_lintcore():
    from strata_kb import lintcore

    rows = [["#", "Decision", "Status", "Owner", "Blocks"], ["D1", "x", "OPEN", "a", "M-demo-US1"]]
    assert lintcore.table_column(rows, "status") == 2
    assert lintcore.table_column(rows, "Blocks") == 4
    assert lintcore.table_column(rows, "nope") is None
    assert lintcore.table_column([], "status") is None
    assert ticketcheck._table_column is lintcore.table_column


def test_parse_decisions_reads_blocks_column():
    text = (
        "# M\n> Mission: M-demo\n\n## Technology decisions\n"
        "| # | Decision | Status | Owner | Blocks |\n|---|---|---|---|---|\n"
        "| D1 | one | DECIDED | a | M-demo-US1, M-demo-US3 |\n"
        "| D2 | two | OPEN | b | M-other-US2 |\n"
        "| D3 | three | OPEN | c |  |\n"
    )
    table = ticketcheck.parse_decisions(text, "m")
    assert table.rows["D1"].blocks == ("M-demo-US1", "M-demo-US3")
    assert table.rows["D2"].blocks == ("M-other-US2",)
    assert table.rows["D3"].blocks == ()


def test_parse_decisions_without_blocks_column_keeps_empty_tuple():
    text = (
        "# M\n> Mission: M-demo\n\n## Technology decisions\n"
        "| # | Decision | Status | Owner |\n|---|---|---|---|\n"
        "| D1 | one | DECIDED | a |\n"
    )
    table = ticketcheck.parse_decisions(text, "m")
    assert table.rows["D1"] == ticketcheck.Decision("D1", "DECIDED", "a", ())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ticketcheck.py -q -k "table_column or blocks_column or without_blocks"`
Expected: FAIL — `AttributeError: module 'strata_kb.lintcore' has no attribute 'table_column'`, then `TypeError`/`AttributeError` on `blocks`.

- [ ] **Step 3: Add `table_column` to `lintcore.py`**

Insert directly after `table_rows` (after line 621):

```python
def table_column(rows: list[list[str]], name: str) -> int | None:
    """Index of the header cell equal to `name` (case-insensitive,
    stripped) in a `table_rows` result, `None` when absent. Columns are
    found by name, never position, so a reordered table still parses."""
    header = [c.strip().lower() for c in rows[0]] if rows else []
    key = name.strip().lower()
    return header.index(key) if key in header else None
```

- [ ] **Step 4: Rewire `ticketcheck.py`**

Replace the `_table_column` definition (lines 491-493) with one alias line so every existing call site keeps working:

```python
_table_column = lintcore.table_column
```

Add the constant after `DECISION_REF_RE` (line 58):

```python
# A full US id inside a table cell (`Blocks`, `Depends on`): the mission
# slug is lowercase kebab-case (mission.MISSION_ID_RE), n >= 1.
US_ID_IN_CELL_RE = re.compile(r"\bM-[a-z0-9]+(?:-[a-z0-9]+)*-US[1-9]\d*\b")
```

Change `Decision` and `parse_decisions`:

```python
@dataclass(frozen=True)
class Decision:
    id: str
    status: str
    owner: str
    blocks: tuple[str, ...] = ()   # US ids in the `Blocks` cell, as written
```

```python
def parse_decisions(text: str, source: str) -> DecisionTable:
    """The `## Technology decisions` table of `text` keyed by its `#` cell.
    Columns are found by header name, so a reordered table still parses;
    no section or no `#`/`Status` header -> empty rows. `blocks` carries
    the full US ids of the `Blocks` cell (empty when the column is absent)."""
    body = lintcore.section_body(text, mission.TECH_DECISIONS_HEADING)
    rows = lintcore.table_rows(body) if body is not None else []
    if not rows:
        return DecisionTable(source, {})
    i_id = _table_column(rows, "#")
    i_status = _table_column(rows, "status")
    i_owner = _table_column(rows, "owner")
    i_blocks = _table_column(rows, "blocks")
    if i_id is None or i_status is None:
        return DecisionTable(source, {})
    out: dict[str, Decision] = {}
    for r in rows[1:]:
        if len(r) <= max(i_id, i_status):
            continue
        owner = r[i_owner].strip() if i_owner is not None and len(r) > i_owner else ""
        blocks_cell = r[i_blocks] if i_blocks is not None and len(r) > i_blocks else ""
        blocks = tuple(dict.fromkeys(US_ID_IN_CELL_RE.findall(blocks_cell)))
        out[r[i_id].strip()] = Decision(r[i_id].strip(), r[i_status].strip(), owner, blocks)
    return DecisionTable(source, out)
```

- [ ] **Step 5: Run the whole ticketcheck suite**

Run: `uv run pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: all PASS (the three new tests plus every existing pin).

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/lintcore.py src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -F <scratchpad>/msg-task1.txt
```
Message: `refactor: share table_column from lintcore; Decision carries its Blocks ids`

---

### Task 2: `missionnext` parsing — stories, dependencies, history

**Depends on:** task 1

**Files:**
- Create: `src/strata_kb/missionnext.py`
- Test: `tests/test_missionnext.py` (create)

**Interfaces:**
- Consumes: `lintcore.section_body`, `lintcore.table_rows`, `lintcore.table_column`, `mission.MISSION_LINE_RE`, `mission.SEQUENCING_HEADING`, `ticketcheck.parse_decisions`, `ticketcheck.DecisionTable`, `ticketcheck.US_ID_IN_CELL_RE`, `ticketcheck.GROUNDED_ON_RE`, `svcnote.ROW_RE`, `mdutils._SEP_ROW_RE`.
- Produces (module `strata_kb.missionnext`):
  - `Story(us_id: str, mission_id: str, title: str, depends_on: tuple[str, ...], seq_index: int | None)` — frozen dataclass.
  - `ParsedMission = tuple[str | None, list[Story], DecisionTable]`.
  - `dep_ids(cell: str, mission_id: str) -> tuple[str, ...]` — full ids as written; bare `US<n>` → `f"{mission_id}-US<n>"`; `none` / `-` / `n/a` / empty → `()`; deduplicated in order.
  - `parse_mission(text: str) -> ParsedMission`.
  - `grounded_repo_id(text: str) -> str | None` — repo qualifier of the first `- Grounded on: <repo>:<doc> @ <rev>` line, else `None`.
  - `done_ids_from_history(history_l2: str | None) -> set[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_missionnext.py`:

```python
"""Engine tests for `kb mission next` (`strata_kb.missionnext`). Text in,
statuses out — no filesystem, no hub."""

from __future__ import annotations

from strata_kb import missionnext

PLATFORM = """# Platform operations
> Mission: M-platform

## US backlog
| US ID | Title |
|---|---|
| M-platform-US1 | Foundation slice |
| M-platform-US2 | Observability |
| M-platform-US3 | Backups |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-platform-US1 | none | L | first |
| M-platform-US2 | US1 | M | bare id |

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.api [arch §3.2] | DECIDED | lead | M-platform-US1 |
| D2 | New svc.metrics | OPEN | Alice | M-platform-US2 |

## Services & order
- Grounded on: myflix:myflix-code @ abc1234
"""

CATALOG = """# Catalog
> Mission: M-catalog

## US backlog
| US ID | Title |
|---|---|
| M-catalog-US1 | Browse titles |
| M-catalog-US2 | Search |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-catalog-US2 | M-catalog-US1, M-platform-US2 | M | cross-mission |
| M-catalog-US1 | M-platform-US1 | S | after foundation |
"""


def test_dep_ids_full_bare_and_none():
    assert missionnext.dep_ids("none", "M-a") == ()
    assert missionnext.dep_ids("-", "M-a") == ()
    assert missionnext.dep_ids("", "M-a") == ()
    assert missionnext.dep_ids("US1", "M-a") == ("M-a-US1",)
    assert missionnext.dep_ids("M-b-US3, US2", "M-a") == ("M-b-US3", "M-a-US2")
    assert missionnext.dep_ids("M-b-US3 and M-b-US3", "M-a") == ("M-b-US3",)
    assert missionnext.dep_ids("after US10 lands (see notes)", "M-a") == ("M-a-US10",)


def test_parse_mission_reads_backlog_sequencing_and_decisions():
    mission_id, stories, decisions = missionnext.parse_mission(PLATFORM)
    assert mission_id == "M-platform"
    assert [s.us_id for s in stories] == ["M-platform-US1", "M-platform-US2", "M-platform-US3"]
    assert stories[0].title == "Foundation slice"
    assert stories[0].depends_on == ()
    assert stories[0].seq_index == 0
    assert stories[1].depends_on == ("M-platform-US1",)
    assert stories[1].seq_index == 1
    assert stories[2].depends_on == ()
    assert stories[2].seq_index is None
    assert decisions.rows["D2"].blocks == ("M-platform-US2",)


def test_parse_mission_without_sequencing_or_decisions():
    text = "# X\n> Mission: M-x\n\n## US backlog\n| US ID | Title |\n|---|---|\n| M-x-US1 | Only |\n"
    mission_id, stories, decisions = missionnext.parse_mission(text)
    assert mission_id == "M-x"
    assert stories == [missionnext.Story("M-x-US1", "M-x", "Only", (), None)]
    assert decisions.rows == {}


def test_parse_mission_without_id_or_backlog():
    mission_id, stories, _ = missionnext.parse_mission("# nothing here\n")
    assert mission_id is None
    assert stories == []


def test_grounded_repo_id():
    assert missionnext.grounded_repo_id(PLATFORM) == "myflix"
    assert missionnext.grounded_repo_id(CATALOG) is None
    assert missionnext.grounded_repo_id("- Grounded on: demo-code @ abc1234\n") is None


HISTORY = """# myflix-svc

> Ticket history, appended by `kb svc note`. Do not edit by hand.

## hist.api api — ticket history

| Ticket | Title | Domain refs |
| --- | --- | --- |
| M-platform-US1 | Foundation slice | arch §3 |

## hist.web web — ticket history

| Ticket | Title | Domain refs |
|:---|:---:|---:|
| M-catalog-US1 | Browse titles | |
| M-platform-US1 | Foundation slice | arch §3 |
"""


def test_done_ids_from_history_reads_every_hist_section():
    assert missionnext.done_ids_from_history(HISTORY) == {"M-platform-US1", "M-catalog-US1"}


def test_done_ids_from_history_handles_missing_text():
    assert missionnext.done_ids_from_history(None) == set()
    assert missionnext.done_ids_from_history("") == set()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_missionnext.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'strata_kb.missionnext'`.

- [ ] **Step 3: Create `src/strata_kb/missionnext.py`**

```python
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
from strata_kb.svcnote import ROW_RE
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
    skips them."""
    out: set[str] = set()
    for raw in (history_l2 or "").splitlines():
        line = raw.strip()
        if not line.startswith("|") or _SEP_ROW_RE.match(line):
            continue
        m = ROW_RE.match(line)
        if m is None:
            continue
        ticket = m.group("ticket").strip()
        if ticket and ticket != "Ticket":
            out.add(ticket)
    return out
```

(`asdict`, `StoryStatus` and `DECIDED` are used by Task 3/4; keep them now so the module does not churn.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_missionnext.py -q`
Expected: 7 PASS.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src/strata_kb/missionnext.py tests/test_missionnext.py`
Expected: clean (remove an unused import only if ruff names it — `asdict`/`StoryStatus`/`DECIDED` are referenced by Task 3/4; if ruff flags `asdict` as unused now, keep it and add `# noqa: F401` until Task 4 uses it, then drop the noqa).

```bash
git add src/strata_kb/missionnext.py tests/test_missionnext.py
git commit -F <scratchpad>/msg-task2.txt
```
Message: `feat: missionnext parses stories, dependencies and -svc history`

---

### Task 3: `missionnext.statuses` — done / drafted / ready / blocked

**Depends on:** task 2

**Files:**
- Modify: `src/strata_kb/missionnext.py` (append)
- Test: `tests/test_missionnext.py` (append)

**Interfaces:**
- Consumes: `Story`, `StoryStatus`, `ParsedMission`, `DecisionTable`, `DECIDED` from Task 2.
- Produces: `statuses(missions: list[ParsedMission], drafted: set[str], done: set[str] | None) -> list[StoryStatus]` — missions in input order; inside a mission, stories with a `seq_index` first (ascending), then the rest in backlog order. Reason strings exactly: `US <id> not done`, `US <id> unknown`, `D<n> <status> (owner: <owner>)` (owner `?` when empty, status as written, `OPEN` when empty).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_missionnext.py`:

```python
def _run(drafted=(), done=None):
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    return {
        s.us_id: s
        for s in missionnext.statuses(parsed, set(drafted), None if done is None else set(done))
    }


def test_first_story_with_decided_row_is_ready():
    s = _run()["M-platform-US1"]
    assert s.status == "ready" and s.reasons == ()


def test_dependency_not_done_blocks_even_when_drafted():
    by = _run(drafted=["M-platform-US1"])
    assert by["M-platform-US1"].status == "drafted"
    assert by["M-platform-US2"].status == "blocked"
    assert by["M-platform-US2"].reasons == (
        "US M-platform-US1 not done",
        "D2 OPEN (owner: Alice)",
    )


def test_done_dependency_and_decided_rows_make_ready():
    by = _run(drafted=["M-platform-US1"], done=["M-platform-US1"])
    assert by["M-platform-US1"].status == "done"
    assert by["M-catalog-US1"].status == "ready"
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: Alice)",)


def test_cross_mission_dependency_and_order():
    order = [s.us_id for s in missionnext.statuses(
        [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)], set(), set()
    )]
    assert order == [
        "M-platform-US1", "M-platform-US2", "M-platform-US3",   # US3 absent from Sequencing → last
        "M-catalog-US2", "M-catalog-US1",                       # Sequencing row order, not backlog
    ]
    by = _run(done=["M-platform-US1", "M-catalog-US1"])
    assert by["M-catalog-US2"].status == "blocked"
    assert by["M-catalog-US2"].reasons == ("US M-platform-US2 not done",)


def test_unknown_dependency_is_named():
    text = CATALOG.replace("M-platform-US1", "M-ghost-US9")
    parsed = [missionnext.parse_mission(text)]
    by = {s.us_id: s for s in missionnext.statuses(parsed, set(), set())}
    assert by["M-catalog-US1"].reasons == ("US M-ghost-US9 unknown",)


def test_no_done_information_never_marks_done():
    by = _run(drafted=["M-platform-US1"], done=None)
    assert by["M-platform-US1"].status == "drafted"
    assert by["M-catalog-US1"].status == "blocked"
    assert by["M-catalog-US1"].reasons == ("US M-platform-US1 not done",)


def test_decision_with_empty_status_and_owner_prints_placeholders():
    text = PLATFORM.replace("| D2 | New svc.metrics | OPEN | Alice |", "| D2 | New svc.metrics |  |  |")
    by = {s.us_id: s for s in missionnext.statuses([missionnext.parse_mission(text)], set(), {"M-platform-US1"})}
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: ?)",)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_missionnext.py -q -k "ready or blocks or order or unknown or never_marks or placeholders"`
Expected: FAIL — `AttributeError: module 'strata_kb.missionnext' has no attribute 'statuses'`.

- [ ] **Step 3: Append `statuses` to `missionnext.py`**

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_missionnext.py -q`
Expected: 14 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/missionnext.py tests/test_missionnext.py
git commit -F <scratchpad>/msg-task3.txt
```
Message: `feat: missionnext derives done / drafted / ready / blocked per story`

---

### Task 4: `missionnext.render` and `to_json`

**Depends on:** task 3

**Files:**
- Modify: `src/strata_kb/missionnext.py` (append)
- Test: `tests/test_missionnext.py` (append)

**Interfaces:**
- Consumes: `StoryStatus` list from Task 3.
- Produces:
  - `next_story(results: list[StoryStatus]) -> StoryStatus | None` — first `ready`.
  - `render(results: list[StoryStatus], notes: list[str]) -> str` — `note: …` lines (then a blank line) when any; the `| US | Mission | Status | Reason |` table; blank line; `Next: <id> — <title>` or `Next: none ready — <b> blocked, <d> drafted, <k> done`.
  - `to_json(results, notes) -> dict` — `{"notes": [...], "stories": [ {us_id, mission_id, title, status, reasons: [...]} ], "next": "<id>" | None}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_missionnext.py`:

```python
def test_render_table_and_next_line():
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-platform-US1"}, {"M-platform-US1"})
    text = missionnext.render(results, [])
    lines = text.splitlines()
    assert lines[0] == "| US | Mission | Status | Reason |"
    assert lines[1] == "|---|---|---|---|"
    assert "| M-platform-US1 | M-platform | done |  |" in lines
    assert "| M-platform-US2 | M-platform | blocked | D2 OPEN (owner: Alice) |" in lines
    assert "| M-catalog-US2 | M-catalog | blocked | US M-platform-US2 not done |" in lines
    assert lines[-1] == "Next: M-catalog-US1 — Browse titles"
    assert lines[-2] == ""


def test_render_notes_come_first_and_none_ready_counts():
    parsed = [missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-catalog-US1"}, None)
    text = missionnext.render(results, ["done: unknown (no repo id — pass --repo-id)"])
    lines = text.splitlines()
    assert lines[0] == "note: done: unknown (no repo id — pass --repo-id)"
    assert lines[1] == ""
    assert lines[2] == "| US | Mission | Status | Reason |"
    assert lines[-1] == "Next: none ready — 1 blocked, 1 drafted, 0 done"


def test_to_json_shape():
    parsed = [missionnext.parse_mission(PLATFORM)]
    results = missionnext.statuses(parsed, set(), set())
    data = missionnext.to_json(results, ["n1"])
    assert set(data) == {"notes", "stories", "next"}
    assert data["notes"] == ["n1"]
    assert data["next"] == "M-platform-US1"
    assert data["stories"][0] == {
        "us_id": "M-platform-US1", "mission_id": "M-platform", "title": "Foundation slice",
        "status": "ready", "reasons": [],
    }
    assert data["stories"][1]["reasons"] == ["US M-platform-US1 not done", "D2 OPEN (owner: Alice)"]
    assert missionnext.to_json([], [])["next"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_missionnext.py -q -k "render or to_json"`
Expected: FAIL — `AttributeError: … has no attribute 'render'`.

- [ ] **Step 3: Append to `missionnext.py`**

```python
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
```

Remove any `# noqa: F401` left on `asdict` in Task 2.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_missionnext.py -q && uv run ruff check src/strata_kb/missionnext.py tests/test_missionnext.py`
Expected: 17 PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/missionnext.py tests/test_missionnext.py
git commit -F <scratchpad>/msg-task4.txt
```
Message: `feat: missionnext renders the status table, Next line and JSON`

---

### Task 5: CLI `kb mission next`

**Depends on:** task 4

**Files:**
- Modify: `src/strata_kb/cli.py` (add a command to `mission_app`, directly after `mission_lint`, ~line 2657)
- Test: `tests/test_cli_mission.py` (append)

**Interfaces:**
- Consumes: `missionnext.parse_mission`, `grounded_repo_id`, `done_ids_from_history`, `statuses`, `render`, `to_json`; `ticketcheck.load_doc_dir`, `load_from_hub`, `DocLoadError`; `_hub_or_exit(hub, kb_dir)`.
- Produces: `kb mission next [--missions-dir DIR] [--tickets-dir DIR] [--repo-id ID] [--kb-dir .kb] [--hub URL] [--json]`. Exit 0 after a report; exit 1 with a red line only when `--missions-dir` (default `missions`) or an explicit `--tickets-dir` is not a directory.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_mission.py`:

```python
# --- kb mission next -------------------------------------------------------

PLATFORM_NEXT = """# Platform operations
> Mission: M-platform

## US backlog
| US ID | Title |
|---|---|
| M-platform-US1 | Foundation slice |
| M-platform-US2 | Observability |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-platform-US1 | none | L | first |
| M-platform-US2 | US1 | M | |

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.airspace-service | DECIDED | lead | M-platform-US1 |

## Services & order
- Grounded on: demo:demo-code @ abc1234
"""


def _ba_layout(tmp_path: Path, *, drafted: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "ba"
    (root / "missions").mkdir(parents=True)
    (root / "tickets").mkdir()
    (root / "missions" / "M-platform.md").write_text(PLATFORM_NEXT, encoding="utf-8")
    for us in drafted:
        (root / "tickets" / f"{us}.md").write_text(f"# {us}\n", encoding="utf-8")
    return root


def _svc_kb(tmp_path: Path) -> Path:
    """A dev-side .kb with demo-code AND demo-svc whose history records
    M-platform-US1 — what CI publishes to the hub after dev-handover."""
    from strata_kb import svcnote
    from strata_kb.codeingest import core
    from tests.fixtures_coderepo import build_code_repo

    repo = tmp_path / "dev"
    repo.mkdir()
    build_code_repo(repo)
    kb_dir = tmp_path / "devkb"
    core.run(core.CodeIngestOptions(
        repo_root=repo, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo", scaffold_svc=True,
    ))
    svcnote.add_note(
        kb_dir, "demo", "airspace-service",
        svcnote.Note(ticket="M-platform-US1", title="Foundation slice", refs=()),
    )
    return kb_dir


def test_mission_next_local_svc_marks_done_and_names_next(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output
    assert "| M-platform-US2 | M-platform | ready |  |" in result.output
    assert result.output.rstrip().endswith("Next: M-platform-US2 — Observability")


def test_mission_next_without_repo_id_reports_unknown_done(tmp_path):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("- Grounded on: demo:demo-code @ abc1234\n", ""), encoding="utf-8"
    )
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: done: unknown (no repo id — pass --repo-id)" in result.output
    assert "| M-platform-US1 | M-platform | drafted |  |" in result.output
    assert "| M-platform-US2 | M-platform | blocked | US M-platform-US1 not done |" in result.output
    assert "Next: none ready — 1 blocked, 1 drafted, 0 done" in result.output


def test_mission_next_svc_absent_on_hub_is_a_note(tmp_path, fed_hub):
    root = _ba_layout(tmp_path)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub),
    ])
    assert result.exit_code == 0, result.output
    assert "note: done: unknown (demo-svc not published" in result.output
    assert "| M-platform-US1 | M-platform | ready |  |" in result.output


def test_mission_next_reads_history_from_the_hub(tmp_path, fed_hub, run_git):
    import shutil

    from strata_kb import models
    from strata_kb.federation import FederationMeta, write_federation_index

    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    kb_dir = _svc_kb(tmp_path)
    entry = fed_hub / "federation" / "demo"
    shutil.copytree(kb_dir / "demo-svc", entry / "demo-svc")
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-svc", title="demo — services", tags=["code"])]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="demo", source_commit="abc1234", published_at="2026-09-24T00:00:00+00:00"),
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "publish demo")
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub), "--json",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["next"] == "M-platform-US2"
    assert [s["status"] for s in data["stories"]] == ["done", "ready"]
    assert data["notes"] == []


def test_mission_next_explicit_repo_id_and_tickets_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path)
    elsewhere = tmp_path / "drafts"
    elsewhere.mkdir()
    (elsewhere / "M-platform-US1.md").write_text("# x\n", encoding="utf-8")
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--tickets-dir", str(elsewhere),
        "--repo-id", "demo", "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output


def test_mission_next_bad_dirs_are_red_lines(tmp_path):
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output
    root = _ba_layout(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--tickets-dir", str(tmp_path / "nope"),
    ])
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output


def test_mission_next_unreadable_mission_is_skipped_with_a_note(tmp_path):
    root = _ba_layout(tmp_path)
    (root / "missions" / "M-bad.md").write_bytes(b"\xff\xfe# bad")
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: skipped" in result.output and "M-bad.md" in result.output
    assert "| M-platform-US1 |" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli_mission.py -q -k mission_next`
Expected: FAIL — typer reports `No such command 'next'` (exit code 2).

- [ ] **Step 3: Add the command to `cli.py`**

Insert after `mission_lint` (after line 2656, before `@app.command()\ndef diff`):

```python
@mission_app.command("next")
def mission_next(
    missions_dir: Path = typer.Option(
        Path("missions"), "--missions-dir", help="Where mission files live"
    ),
    tickets_dir: Path | None = typer.Option(
        None,
        "--tickets-dir",
        help="Where ticket files live (default: the missions dir's sibling 'tickets/')",
    ),
    repo_id: str = typer.Option(
        "",
        "--repo-id",
        help="Product repo id whose <repo-id>-svc history marks stories done "
        "(default: the repo in the missions' 'Grounded on:' line)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (empty = config); consulted only when the "
        "-svc document is not under --kb-dir",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
) -> None:
    """Which story next: every backlog story across missions/ as done /
    drafted / ready / blocked. Done is derived from the hub's <repo>-svc
    history (kb svc note rows). Read-only; exit 0 after a report."""
    from strata_kb import missionnext, ticketcheck

    for label, d in (("--missions-dir", missions_dir), ("--tickets-dir", tickets_dir)):
        if d is not None and not d.is_dir():
            typer.secho(
                f"{label} '{d}' does not exist or is not a directory", fg=typer.colors.RED
            )
            raise typer.Exit(1)

    notes: list[str] = []
    parsed: list[missionnext.ParsedMission] = []
    texts: list[str] = []
    for path in sorted(missions_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            notes.append(f"skipped {path}: {exc}")
            continue
        text = unicodedata.normalize("NFC", text)
        texts.append(text)
        parsed.append(missionnext.parse_mission(text))

    resolved_tickets = tickets_dir if tickets_dir is not None else missions_dir.parent / "tickets"
    drafted: set[str] = set()
    if resolved_tickets.is_dir():
        drafted = {p.stem for p in resolved_tickets.glob("*.md")}
    else:
        notes.append(f"tickets dir '{resolved_tickets}' not found — no story reads as drafted")

    rid = repo_id or next((r for r in map(missionnext.grounded_repo_id, texts) if r), None)
    done: set[str] | None = None
    if not rid:
        notes.append("done: unknown (no repo id — pass --repo-id)")
    else:
        doc_id = f"{rid}-svc"
        local = kb_dir / doc_id
        doc = None
        try:
            if (local / "_manifest.yaml").exists():
                doc = ticketcheck.load_doc_dir(local, str(local))
            else:
                handle = _hub_or_exit(hub, kb_dir)
                doc = ticketcheck.load_from_hub(handle.federation_dir, rid, doc_id)
        except ticketcheck.DocLoadError as exc:
            notes.append(f"done: unknown ({exc})")
        if doc is None and not any(n.startswith("done: unknown") for n in notes):
            notes.append(
                f"done: unknown ({doc_id} not published — the Dev repo has not run "
                "dev-code-seed, or CI has not published yet)"
            )
        if doc is not None:
            done = missionnext.done_ids_from_history(doc.read_group("history"))

    results = missionnext.statuses(parsed, drafted, done)
    if json_output:
        typer.echo(json.dumps(missionnext.to_json(results, notes)))
    else:
        typer.echo(missionnext.render(results, notes))
```

`json` is already imported at the top of `cli.py`; `unicodedata` is not — add `import unicodedata` to the stdlib import block (between `import sys` and `from enum import Enum`, line 6-7). `missionlint.lint` normalizes to NFC the same way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_cli_mission.py -q`
Expected: all PASS (7 new + existing).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check src/strata_kb/cli.py tests/test_cli_mission.py`

```bash
git add src/strata_kb/cli.py tests/test_cli_mission.py
git commit -F <scratchpad>/msg-task5.txt
```
Message: `feat: kb mission next — which story is done, drafted, ready or blocked`

---

### Task 6: README, CHANGELOG, spec correction, full suite, graph check

**Depends on:** task 5

**Files:**
- Modify: `README.md:273` (command overview table) and `README.md:684` (BA gates table)
- Modify: `CHANGELOG.md:5` (insert `## Unreleased` above `## 1.3.0`)
- Modify: `docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md` §3.1, §3.2
- Test: `tests/test_cli_mission.py` (append one doc test)

**Interfaces:**
- Consumes: nothing new.
- Produces: documentation only.

- [ ] **Step 1: Write the failing doc test**

Append to `tests/test_cli_mission.py`:

```python
def test_docs_name_the_next_command():
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "| `kb mission next` | Which story next: done / drafted / ready / blocked across `missions/`, done derived from the hub's `<repo>-svc` history |" in readme
    assert "`kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]`" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## Unreleased") < changelog.index("## 1.3.0")
    assert "`kb mission next`" in changelog
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_cli_mission.py -q -k docs_name_the_next`
Expected: FAIL on the README assertion.

- [ ] **Step 3: README**

After line 273 (`| \`kb mission lint\` | … |`) insert:

```markdown
| `kb mission next` | Which story next: done / drafted / ready / blocked across `missions/`, done derived from the hub's `<repo>-svc` history |
```

After line 685 (the `kb ticket check` row of the BA gates table) insert:

```markdown
| `kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]` | Read-only: every backlog story across `missions/` as `done` (its id is in a `hist.*` row of the hub's `<repo-id>-svc`), `drafted` (`tickets/<us-id>.md` exists), `ready` (no ticket, every `Depends on` done, every D-row that `Blocks` it `DECIDED`) or `blocked` (reasons named); ends with `Next: <us-id> — <title>`. `--repo-id` defaults to the repo in the missions' `Grounded on:` line; without one, or when `-svc` is not on the hub, a note says done is unknown | `0` always (`1` only for a bad directory flag) |
```

- [ ] **Step 4: CHANGELOG**

Insert above `## 1.3.0 — 2026-09-24`:

```markdown
## Unreleased

- `kb mission next`: read-only report of every backlog story across `missions/` as `done` / `drafted` / `ready` / `blocked`, ending with `Next: <us-id> — <title>`. `done` is derived from the hub's `<repo-id>-svc` history tables (the rows `kb svc note` writes at dev-handover and CI publishes on merge) — never from a status column; `ready` needs every `Depends on` story done and every `## Technology decisions` row that `Blocks` the story `DECIDED`; `Depends on` may name a story of another mission. `Decision` rows now carry their `Blocks` ids; `lintcore.table_column` is the shared header-name column lookup. Exit 0 always — it is a query, not a gate.
```

- [ ] **Step 5: Spec correction**

In `docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md`:

- §3.2, replace the bullet beginning "Backlog ids and titles: the row loop of `missionlint.check_backlog` is extracted…" with:
  `- Backlog ids and titles: \`lintcore.table_rows(lintcore.section_body(text, "## US backlog"))[1:]\` — cells 0 and 1. \`check_backlog\` is HIGH impact (\`mission_lint\` and \`ticket_lint\` route through it) and is not touched; the DoR gate keeps validating the table, this query only reads it.`
- §3.1, replace "Exit code 0 always. Read errors on a mission file…" with: `Exit code 0 after a report; exit 1 with a red line only when \`--missions-dir\` (default \`missions/\`) or an explicit \`--tickets-dir\` is not a directory, as \`kb ticket check\` does. A mission file that cannot be read is reported as a note naming the file and skipped, never a crash.`
- §3.1, hub bullet: prepend `Local first: \`<kb-dir>/<repo-id>-svc\` when its manifest exists (a dev machine), else the hub —` before "Hub via `_hub_or_exit`…".
- §7 PR 1 line: drop `missionlint.parse_backlog`, add `lintcore.table_column`.

- [ ] **Step 6: Run the doc test, then the full suite and lint in the foreground**

Run: `uv run pytest tests/test_cli_mission.py -q -k docs_name_the_next`
Expected: PASS.

Run: `uv run pytest -q` (takes ~17 minutes here; let it block) and `uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 7: Graph change analysis, then commit**

Call `mcp__gitnexus__detect_changes({scope: "all"})` and paste its summary into the task report. `partial: true` or `truncated: true` → re-run; do not commit on an incomplete result.

```bash
git add README.md CHANGELOG.md docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md tests/test_cli_mission.py
git commit -F <scratchpad>/msg-task6.txt
```
Message: `docs: kb mission next in README and CHANGELOG; spec reads the backlog via table_rows`

---

## Self-review

- **Spec coverage (§3, §6, §7 PR 1):** CLI flags and defaults — Task 5; statuses and reason strings — Task 3; ordering — Task 3 (`_mission_order`); `Next:` both forms and JSON — Task 4; `Decision.blocks` — Task 1; `-svc` history parse — Task 2; hub/local/notes — Task 5; README row and CHANGELOG — Task 6; `detect_changes` before commit — Task 6. Not covered on purpose: `parse_backlog` extraction (HIGH-impact symbol; spec corrected in Task 6).
- **Placeholders:** none; every step carries code or an exact command.
- **Type consistency:** `ParsedMission` is `tuple[str | None, list[Story], DecisionTable]` in Tasks 2, 3, 5; `statuses(missions, drafted: set[str], done: set[str] | None)` in Tasks 3, 4, 5; `render(results, notes)` / `to_json(results, notes)` in Tasks 4, 5; `lintcore.table_column(rows, name)` in Tasks 1, 2; `Decision.blocks: tuple[str, ...]` in Tasks 1, 3.
