# Ticket status model, Grounded-on parsing, NFR N/A, ticket folders — PR1 (engine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb mission next` reports five statuses (`done` / `ready` / `draft` / `to-draft` / `blocked`), reads a comma-separated `Grounded on:` line, reads tickets under `tickets/<folder>/`, and `kb ticket tidy` moves a flat `tickets/` into folders; `kb ticket lint` accepts `N/A — <reason>` as an NFR target; the `ba-ticket-author` wrappers print every `note:` line and save into folders.

**Architecture:** Pure text/set engines stay pure (`missionnext.py`, new `tickettidy.py` plan half); `cli.py` does filesystem and hub. `ticketcheck.GROUNDED_ON_RE` stays the single-entry pattern; a new `grounded_entries()` splits a list and `missionnext.grounded_doc` picks the `-code` entry. Every reader of `tickets/` accepts both the flat and the folder layout.

**Tech Stack:** Python 3.11+, typer CLI, pytest. Spec: `docs/superpowers/specs/2026-09-29-ticket-status-decision-defaults-design.md` §3, §4, §6 (lint line only), §7, §9.

## Global Constraints

- Before editing any function/class, run impact analysis per `CLAUDE.md`: MCP `impact({target: "<symbol>", direction: "upstream"})`, or CLI `node .gitnexus/run.cjs impact "<symbol>" --direction upstream --repo .`. Report callers; HIGH/CRITICAL risk is a warning to state, `UNKNOWN` is confirmed with `grep -rn`.
- Before each commit run `detect_changes({scope: "all"})` (or `node .gitnexus/run.cjs detect-changes --scope all --repo .`).
- The git commit hook rejects `-n` in the commit command line — never pass `--no-verify`.
- Commit messages: `<type>: <description>` (feat/fix/refactor/docs/test/chore), ending with the line `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Status names are exactly: `done`, `ready`, `draft`, `to-draft`, `blocked`. `Next:` names the first `to-draft` story.
- `Grounded on:` list separator is `,`. The `-code` entry wins; else the first entry.
- NFR `N/A` shape: `^N/A\s*[—-]\s*\S` (a reason is mandatory).
- Folder layout: `tickets/<mission-id>/<ticket-id>.md`. Readers never fail on a flat file.
- `kb ticket tidy` exits 0 always, never calls git.
- Test runner: `uv run pytest <path> -q` from the repo root. Full suite: `uv run pytest -q`.
- Version bump to `1.6.0` (breaking JSON `status` values, CHANGELOG says so).

---

## File map

| File | Change |
|---|---|
| `src/strata_kb/ticketcheck.py` | add `grounded_entries()` next to `GROUNDED_ON_RE` (line 40) |
| `src/strata_kb/missionnext.py` | `grounded_doc` uses `grounded_entries`; `dor_counts()`; `statuses()` takes `dict[str, tuple[int,int]]`; five statuses; `_next_line`, `render` text |
| `src/strata_kb/missionlint.py` | `check_grounded_on()` warning; `check_coverage` looks in `tickets/<mission-id>/` first |
| `src/strata_kb/acquality.py` | `nfr_target_ok` accepts `N/A — <reason>` |
| `src/strata_kb/cli.py` | `mission next`: `rglob`, DoR counts; `_resolve_missions_dir` walks ancestors; new `ticket tidy` command |
| `src/strata_kb/tickettidy.py` | new: `plan_moves`, `apply_moves` |
| `src/strata_kb/usage/transcript.py` | `TICKET_PATH_RE` allows one folder |
| `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`, `claude-command-ba-ticket-author.md`, `cursor-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md` | Intake prints notes, runs tidy; new status names; folder save path |
| `src/strata_kb/templates/init/mission-template.md` | line 93: list allowed |
| `src/strata_kb/templates/init/QUICKSTART-ba.md` | status table, folder path |
| `README.md`, `CHANGELOG.md`, `pyproject.toml` | docs + 1.6.0 |
| tests | `test_missionnext.py`, `test_ticketcheck.py`, `test_missionlint.py`, `test_acquality.py`, `test_cli_mission.py`, `test_cli_ticket_tidy.py` (new), `test_usage_transcript.py`, `test_templates.py` |

---

### Task 1: `grounded_entries()` and a lenient `grounded_doc`

**Files:**
- Modify: `src/strata_kb/ticketcheck.py:38-44`
- Modify: `src/strata_kb/missionnext.py:113-124` (`grounded_doc`)
- Test: `tests/test_missionnext.py`, `tests/test_ticketcheck.py`

**Interfaces:**
- Produces: `ticketcheck.grounded_entries(line: str) -> list[tuple[str | None, str, str]]` — `(repo, doc, rev_lowercase)` per comma-separated entry; `[]` when the line is not a `Grounded on:` line or any entry is malformed.
- Produces: `missionnext.grounded_doc(text) -> tuple[str | None, str] | None` unchanged signature, now prefers the `-code` entry.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_missionnext.py` after `test_grounded_doc_returns_repo_and_doc`:

```python
def test_grounded_doc_reads_a_comma_separated_list_and_prefers_code():
    two = "- Grounded on: myflix:myflix-svc @ 2946696, myflix:myflix-code @ 2946696\n"
    assert missionnext.grounded_doc(two) == ("myflix", "myflix-code")
    no_code = "- Grounded on: myflix:myflix-svc @ 2946696, myflix:arch @ 2946696\n"
    assert missionnext.grounded_doc(no_code) == ("myflix", "myflix-svc")
    malformed = "- Grounded on: myflix:myflix-code (rev 2946696), myflix:myflix-svc @ 2946696\n"
    assert missionnext.grounded_doc(malformed) is None
```

Append to `tests/test_ticketcheck.py`:

```python
def test_grounded_entries_splits_a_list_and_rejects_a_bad_entry():
    from strata_kb.ticketcheck import grounded_entries

    assert grounded_entries("- Grounded on: demo:demo-code @ ABC1234") == [("demo", "demo-code", "abc1234")]
    assert grounded_entries("- Grounded on: a:a-code @ 1234567, a:a-svc @ 1234567") == [
        ("a", "a-code", "1234567"), ("a", "a-svc", "1234567"),
    ]
    assert grounded_entries("- Grounded on: a:a-code @ 1234567, junk") == []
    assert grounded_entries("- Files: x.py") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_missionnext.py::test_grounded_doc_reads_a_comma_separated_list_and_prefers_code tests/test_ticketcheck.py::test_grounded_entries_splits_a_list_and_rejects_a_bad_entry -q`
Expected: FAIL — `ImportError: cannot import name 'grounded_entries'` and `assert None == ("myflix", "myflix-code")`.

- [ ] **Step 3: Implement**

In `src/strata_kb/ticketcheck.py`, directly after the `GROUNDED_ON_RE` definition (after line 44) add:

```python
_GROUNDED_PREFIX_RE = re.compile(r"^-\s*Grounded on:\s*(?P<rest>.*)$")


def grounded_entries(line: str) -> list[tuple[str | None, str, str]]:
    """`(repo, doc, rev)` per comma-separated entry of a `- Grounded on:`
    line. The mission template shows one entry; the SA writes the `-code`
    and `-svc` docs on one line, so the list is accepted here. Any entry
    that is not `[<repo>:]<doc> @ <rev>` makes the whole line unparseable
    (`[]`) — a half-read line would silently ground on the wrong doc."""
    m = _GROUNDED_PREFIX_RE.match(line.strip())
    if m is None:
        return []
    out: list[tuple[str | None, str, str]] = []
    for part in m.group("rest").split(","):
        em = GROUNDED_ON_RE.match(f"- Grounded on: {part.strip()}")
        if em is None:
            return []
        out.append((em.group("repo"), em.group("doc"), em.group("rev").lower()))
    return out
```

In `src/strata_kb/missionnext.py` replace `grounded_doc`:

```python
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
```

Add `grounded_entries` to the `from strata_kb.ticketcheck import (...)` block at the top of `missionnext.py` (keep `GROUNDED_ON_RE` in the import only if still used; it is not — remove it).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_missionnext.py tests/test_ticketcheck.py -q`
Expected: all PASS, including the pre-existing `test_grounded_doc_returns_repo_and_doc` (single entry, `mid/repo-x` nesting) and the ticket-side `Grounded on:` error tests (`_grounded_on` still uses `GROUNDED_ON_RE` and still rejects a two-entry line on a ticket).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/ticketcheck.py src/strata_kb/missionnext.py tests/test_missionnext.py tests/test_ticketcheck.py
git commit -m "fix: kb mission next reads a comma-separated Grounded on line, prefers the -code entry

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: `kb mission lint` warns on an unparseable `Grounded on:`

**Files:**
- Modify: `src/strata_kb/missionlint.py` (new `check_grounded_on`, wired in `lint()` after `check_technology_decisions`)
- Test: `tests/test_missionlint.py`

**Interfaces:**
- Consumes: `ticketcheck.grounded_entries`, `ticketcheck.SERVICES_HEADING` (`"## Services & order"`).
- Produces: `missionlint.check_grounded_on(text: str) -> list[Issue]` — one warning or `[]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_missionlint.py`:

```python
# --- check 13: Grounded on parseable ---


def test_grounded_on_list_is_parseable_and_silent():
    from strata_kb import missionlint

    text = "## Services & order\n- Grounded on: a:a-code @ 1234567, a:a-svc @ 1234567\n"
    assert missionlint.check_grounded_on(text) == []


def test_grounded_on_unparseable_is_a_warning_naming_mission_next():
    from strata_kb import missionlint

    text = "## Services & order\n- Grounded on: a-code (rev 1234567)\n"
    (issue,) = missionlint.check_grounded_on(text)
    assert issue.level == "warning"
    assert issue.message == (
        "no parseable 'Grounded on: <repo>:<doc> @ <rev>' line in "
        "'## Services & order' — kb mission next cannot derive done"
    )


def test_grounded_on_absent_section_is_silent():
    from strata_kb import missionlint

    assert missionlint.check_grounded_on("## US backlog\n| US ID | Title |\n") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_missionlint.py -k grounded_on -q`
Expected: FAIL — `AttributeError: module 'strata_kb.missionlint' has no attribute 'check_grounded_on'`.

- [ ] **Step 3: Implement**

In `src/strata_kb/missionlint.py` add the import `from strata_kb.ticketcheck import SERVICES_HEADING, grounded_entries` under the existing `from strata_kb import acquality, lintcore, mission` line. Add before `def lint(`:

```python
def check_grounded_on(text: str) -> list[Issue]:
    """Check 13. `kb mission next` derives `done` from the `-code` doc named
    on the `Grounded on:` line. A line it cannot parse is a silent
    `done: unknown` there, so name it here. Warning, not error: a mission is
    authored before the SA grounds it."""
    body = lintcore.section_body(text, SERVICES_HEADING)
    if body is None:
        return []
    if any(grounded_entries(line) for line in body.splitlines()):
        return []
    return [
        Issue(
            "warning",
            "no parseable 'Grounded on: <repo>:<doc> @ <rev>' line in "
            f"'{SERVICES_HEADING}' — kb mission next cannot derive done",
        )
    ]
```

In `lint()`, after `issues += check_technology_decisions(text)` add `issues += check_grounded_on(text)`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_missionlint.py tests/test_cli_mission.py -q`
Expected: PASS. If a fixture mission with an empty `## Services & order` now gets a warning, that is correct behaviour; only `passed` (errors) matters to those tests.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/missionlint.py tests/test_missionlint.py
git commit -m "feat: kb mission lint warns when no Grounded on line parses

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: NFR target accepts `N/A — <reason>`

**Files:**
- Modify: `src/strata_kb/acquality.py:231-233`
- Test: `tests/test_acquality.py:224-231`

**Interfaces:**
- Produces: `acquality.nfr_target_ok(cell) -> bool` — True for a digit, an owned `OPEN(<owner>)`, or `N/A — <reason>`.

- [ ] **Step 1: Extend the failing test**

In `tests/test_acquality.py::test_nfr_target_ok` add these lines at the end of the function:

```python
    assert acquality.nfr_target_ok("N/A — no NFR source in KB") is True
    assert acquality.nfr_target_ok("N/A - no NFR source in KB") is True
    assert acquality.nfr_target_ok("N/A") is False
    assert acquality.nfr_target_ok("N/A —") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_acquality.py::test_nfr_target_ok -q`
Expected: FAIL on `nfr_target_ok("N/A — no NFR source in KB") is True`.

- [ ] **Step 3: Implement**

Replace `nfr_target_ok` in `src/strata_kb/acquality.py`:

```python
_NFR_NA_RE = re.compile(r"^N/A\s*[—-]\s*\S", re.IGNORECASE)


def nfr_target_ok(cell: str) -> bool:
    """An NFR Target is a number, an owned unknown, or `N/A — <reason>`
    (the KB holds no number for this concern) — never a mood, and never a
    bare `N/A`: the reason is what tells the Dev nothing was forgotten."""
    text = cell.strip()
    return (
        bool(re.search(r"\d", text))
        or bool(owned_open_markers(text))
        or _NFR_NA_RE.match(text) is not None
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_acquality.py tests/test_ticketlint.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/acquality.py tests/test_acquality.py
git commit -m "feat: NFR Target accepts 'N/A — <reason>' when the KB holds no number

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Five statuses in `missionnext.statuses`

**Files:**
- Modify: `src/strata_kb/missionnext.py` (`StoryStatus` doc, new `dor_counts`, `statuses`, `next_story`, `_next_line`)
- Test: `tests/test_missionnext.py`

**Interfaces:**
- Produces: `missionnext.dor_counts(text: str) -> tuple[int, int]` — `(ticked, total)` checkboxes under `## Definition of Ready`; `(0, 0)` without the section.
- Produces: `missionnext.statuses(missions, drafted: dict[str, tuple[int, int]], done: set[str] | None) -> list[StoryStatus]`. `drafted` maps ticket id → `dor_counts` of its file.
- Produces: statuses `done | ready | draft | to-draft | blocked`; `next_story` returns the first `to-draft`.

- [ ] **Step 1: Rewrite the status tests**

In `tests/test_missionnext.py` replace `_run` and every test from `test_first_story_with_decided_row_is_ready` through `test_to_json_shape` with:

```python
FULL = (8, 8)
PART = (5, 8)


def _run(drafted=None, done=None):
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    return {
        s.us_id: s
        for s in missionnext.statuses(parsed, dict(drafted or {}), None if done is None else set(done))
    }


def test_dor_counts_reads_the_checklist():
    text = "## Definition of Ready\n- [x] a\n- [ ] b\n- [X] c\n\n## Review record\n- [ ] not counted\n"
    assert missionnext.dor_counts(text) == (2, 3)
    assert missionnext.dor_counts("# T\n## Summary\nx\n") == (0, 0)


def test_first_story_with_decided_row_is_to_draft():
    s = _run()["M-platform-US1"]
    assert s.status == "to-draft" and s.reasons == ()


def test_ticket_file_with_every_dor_box_ticked_is_ready():
    s = _run(drafted={"M-platform-US1": FULL})["M-platform-US1"]
    assert s.status == "ready" and s.reasons == ()


def test_ticket_file_with_unticked_dor_is_draft_with_the_count():
    s = _run(drafted={"M-platform-US1": PART})["M-platform-US1"]
    assert s.status == "draft" and s.reasons == ("DoR 5/8 ticked",)


def test_ticket_file_without_dor_section_is_draft():
    s = _run(drafted={"M-platform-US1": (0, 0)})["M-platform-US1"]
    assert s.status == "draft" and s.reasons == ("no Definition of Ready section",)


def test_dependency_not_done_blocks_even_when_ready():
    by = _run(drafted={"M-platform-US1": FULL})
    assert by["M-platform-US1"].status == "ready"
    assert by["M-platform-US2"].status == "blocked"
    assert by["M-platform-US2"].reasons == (
        "US M-platform-US1 not done",
        "D2 OPEN (owner: Alice)",
    )


def test_done_wins_over_a_ticket_file():
    by = _run(drafted={"M-platform-US1": PART}, done=["M-platform-US1"])
    assert by["M-platform-US1"].status == "done"
    assert by["M-catalog-US1"].status == "to-draft"
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: Alice)",)


def test_cross_mission_dependency_and_order():
    order = [s.us_id for s in missionnext.statuses(
        [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)], {}, set()
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
    by = {s.us_id: s for s in missionnext.statuses(parsed, {}, set())}
    assert by["M-catalog-US1"].reasons == ("US M-ghost-US9 unknown",)


def test_no_done_information_never_marks_done():
    by = _run(drafted={"M-platform-US1": FULL}, done=None)
    assert by["M-platform-US1"].status == "ready"
    assert by["M-catalog-US1"].status == "blocked"
    assert by["M-catalog-US1"].reasons == ("US M-platform-US1 not done",)


def test_decision_with_empty_status_and_owner_prints_placeholders():
    text = PLATFORM.replace("| D2 | New svc.metrics | OPEN | Alice |", "| D2 | New svc.metrics |  |  |")
    by = {s.us_id: s for s in missionnext.statuses([missionnext.parse_mission(text)], {}, {"M-platform-US1"})}
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: ?)",)


def test_bare_us_id_in_blocks_cell_blocks_its_story():
    text = PLATFORM.replace(
        "| D2 | New svc.metrics | OPEN | Alice | M-platform-US2 |",
        "| D2 | New svc.metrics | OPEN | Alice | US2 |",
    )
    by = {s.us_id: s for s in missionnext.statuses([missionnext.parse_mission(text)], {}, {"M-platform-US1"})}
    assert by["M-platform-US2"].status == "blocked"
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: Alice)",)


def test_lowercase_decided_status_still_counts_as_decided():
    text = PLATFORM.replace(
        "| D1 | New svc.api [arch §3.2] | DECIDED | lead | M-platform-US1 |",
        "| D1 | New svc.api [arch §3.2] | decided | lead | M-platform-US1 |",
    )
    by = {s.us_id: s for s in missionnext.statuses([missionnext.parse_mission(text)], {}, set())}
    assert by["M-platform-US1"].status == "to-draft"
    assert by["M-platform-US1"].reasons == ()


def test_render_table_and_next_line():
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-platform-US1": FULL}, {"M-platform-US1"})
    text = missionnext.render(results, [])
    lines = text.splitlines()
    assert lines[0] == "| US | Mission | Status | Reason |"
    assert lines[1] == "|---|---|---|---|"
    assert "| M-platform-US1 | M-platform | done |  |" in lines
    assert "| M-platform-US2 | M-platform | blocked | D2 OPEN (owner: Alice) |" in lines
    assert "| M-catalog-US2 | M-catalog | blocked | US M-catalog-US1 not done; US M-platform-US2 not done |" in lines
    # M-platform-US3 has no dependency and no D-row, so it is the first
    # to-draft story in output order (before any M-catalog story).
    assert lines[-1] == "Next: M-platform-US3 — Backups"
    assert lines[-2] == ""


def test_render_notes_come_first_and_none_to_draft_counts():
    parsed = [missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-catalog-US1": PART}, None)
    text = missionnext.render(results, ["done: unknown (no repo id — pass --repo-id)"])
    lines = text.splitlines()
    assert lines[0] == "note: done: unknown (no repo id — pass --repo-id)"
    assert lines[1] == ""
    assert lines[2] == "| US | Mission | Status | Reason |"
    assert "| M-catalog-US1 | M-catalog | draft | DoR 5/8 ticked |" in lines
    assert lines[-1] == "Next: none to draft — 1 blocked, 1 draft, 0 ready, 0 done"


def test_to_json_shape():
    parsed = [missionnext.parse_mission(PLATFORM)]
    results = missionnext.statuses(parsed, {}, set())
    data = missionnext.to_json(results, ["n1"])
    assert set(data) == {"notes", "stories", "next"}
    assert data["notes"] == ["n1"]
    assert data["next"] == "M-platform-US1"
    assert data["stories"][0] == {
        "us_id": "M-platform-US1", "mission_id": "M-platform", "title": "Foundation slice",
        "status": "to-draft", "reasons": [],
    }
    assert data["stories"][1]["reasons"] == ["US M-platform-US1 not done", "D2 OPEN (owner: Alice)"]
    assert missionnext.to_json([], [])["next"] is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_missionnext.py -q`
Expected: FAIL — `AttributeError: ... 'dor_counts'`, `TypeError` on the dict argument, and `'ready' != 'to-draft'`.

- [ ] **Step 3: Implement**

In `src/strata_kb/missionnext.py`:

Update the module docstring first line to `"""`kb mission next` engine — which story is done, ready, draft, to-draft or blocked.` and the `StoryStatus.status` comment to `# done | ready | draft | to-draft | blocked`.

Add after `done_ids_from_history`:

```python
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
```

Replace `statuses`:

```python
def statuses(
    missions: list[ParsedMission], drafted: dict[str, tuple[int, int]], done: set[str] | None
) -> list[StoryStatus]:
    """One `StoryStatus` per backlog story, first rule that matches:
    done (id in `done`) → ready (ticket file, every DoR box ticked) → draft
    (ticket file, some box unticked, or no DoR section) → to-draft (no
    file, every dependency done, every D-row blocking it DECIDED) →
    blocked, with one reason per cause. `drafted` maps a ticket id to its
    `dor_counts`. `done=None` means the hub could not answer: nothing is
    done, and the caller says why in a note."""
    known = {s.us_id for _m, stories, _d in missions for s in stories}
    done_set = done or set()
    out: list[StoryStatus] = []
    for mission_id, stories, decisions in missions:
        # A `Blocks` cell may hold a bare `US<n>` (spec §3.2: same id rule as
        # `Depends on`); resolve it against this mission's id once, not once
        # per story.
        blocking = [
            (d, set(dep_ids(" ".join(d.blocks), mission_id or "")))
            for d in decisions.rows.values()
        ]
        for s in _mission_order(stories):
            if s.us_id in done_set:
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "done", ()))
                continue
            if s.us_id in drafted:
                ticked, total = drafted[s.us_id]
                if total and ticked == total:
                    out.append(StoryStatus(s.us_id, s.mission_id, s.title, "ready", ()))
                    continue
                why = f"DoR {ticked}/{total} ticked" if total else "no Definition of Ready section"
                out.append(StoryStatus(s.us_id, s.mission_id, s.title, "draft", (why,)))
                continue
            reasons: list[str] = []
            for dep in s.depends_on:
                if dep in done_set:
                    continue
                reasons.append(f"US {dep} not done" if dep in known else f"US {dep} unknown")
            for d, blocks in blocking:
                if s.us_id in blocks and d.status.strip().upper() != DECIDED:
                    reasons.append(f"{d.id} {d.status.strip() or 'OPEN'} (owner: {d.owner or '?'})")
            status = "blocked" if reasons else "to-draft"
            out.append(StoryStatus(s.us_id, s.mission_id, s.title, status, tuple(reasons)))
    return out


def next_story(results: list[StoryStatus]) -> StoryStatus | None:
    return next((r for r in results if r.status == "to-draft"), None)


def _next_line(results: list[StoryStatus]) -> str:
    nxt = next_story(results)
    if nxt is not None:
        return f"Next: {nxt.us_id} — {nxt.title}"
    count = {k: sum(1 for r in results if r.status == k) for k in ("blocked", "draft", "ready", "done")}
    return (
        f"Next: none to draft — {count['blocked']} blocked, {count['draft']} draft, "
        f"{count['ready']} ready, {count['done']} done"
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_missionnext.py -q`
Expected: PASS. `tests/test_cli_mission.py` now fails (it passes a set) — Task 5 fixes it.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/missionnext.py tests/test_missionnext.py
git commit -m "feat: kb mission next engine — done / ready / draft / to-draft / blocked from the DoR checklist

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: `kb mission next` CLI reads nested tickets and DoR counts

**Files:**
- Modify: `src/strata_kb/cli.py:2936-2941` (the `resolved_tickets` / `drafted` block in `mission_next`)
- Test: `tests/test_cli_mission.py`

**Interfaces:**
- Consumes: `missionnext.dor_counts`, `missionnext.statuses(..., drafted: dict, ...)`.

- [ ] **Step 1: Update and add CLI tests**

In `tests/test_cli_mission.py` replace `_ba_layout` with:

```python
DOR_FULL = "## Definition of Ready\n- [x] a\n- [x] b\n"
DOR_PART = "## Definition of Ready\n- [x] a\n- [ ] b\n"


def _ba_layout(
    tmp_path: Path, *, drafted: tuple[str, ...] = (), dor: str = DOR_FULL, nested: bool = False
) -> Path:
    root = tmp_path / "ba"
    (root / "missions").mkdir(parents=True)
    (root / "tickets").mkdir()
    (root / "missions" / "M-platform.md").write_text(PLATFORM_NEXT, encoding="utf-8")
    for us in drafted:
        folder = root / "tickets" / "M-platform" if nested else root / "tickets"
        folder.mkdir(exist_ok=True)
        (folder / f"{us}.md").write_text(f"# {us}\n\n{dor}", encoding="utf-8")
    return root
```

Then apply these edits to the existing tests:

- `test_mission_next_local_svc_marks_done_and_names_next`: change `| M-platform-US2 | M-platform | ready |  |` to `| M-platform-US2 | M-platform | to-draft |  |`.
- `test_mission_next_without_repo_id_reports_unknown_done`: change `| M-platform-US1 | M-platform | drafted |  |` to `| M-platform-US1 | M-platform | ready |  |` and the last assert to `"Next: none to draft — 1 blocked, 0 draft, 1 ready, 0 done"`.
- `test_mission_next_svc_absent_on_hub_is_a_note` and `test_mission_next_no_hub_configured_is_a_note_not_a_red_line`: `ready` → `to-draft` in the US1 row.
- `test_mission_next_reads_history_from_the_hub`: `["done", "ready"]` → `["done", "to-draft"]`.
- `test_mission_next_explicit_repo_id_and_tickets_dir`: unchanged (US1 is `done`).

Add:

```python
def test_mission_next_reads_tickets_in_mission_folders(tmp_path):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",), dor=DOR_PART, nested=True)
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | draft | DoR 1/2 ticked |" in result.output


def test_mission_next_ticket_without_dor_section_is_draft(tmp_path):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",), dor="")
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | draft | no Definition of Ready section |" in result.output


def test_mission_next_unreadable_ticket_is_a_note_and_a_draft(tmp_path):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    (root / "tickets" / "M-platform-US1.md").write_bytes(b"\xff\xfe# bad\n")
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: skipped ticket" in result.output
    assert "| M-platform-US1 | M-platform | draft | no Definition of Ready section |" in result.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli_mission.py -k mission_next -q`
Expected: FAIL — `TypeError`/`AttributeError` from the set argument and the new status text.

- [ ] **Step 3: Implement**

In `src/strata_kb/cli.py::mission_next` replace the block

```python
    resolved_tickets = tickets_dir if tickets_dir is not None else missions_dir.parent / "tickets"
    drafted: set[str] = set()
    if resolved_tickets.is_dir():
        drafted = {p.stem for p in resolved_tickets.glob("*.md")}
    else:
        notes.append(f"tickets dir '{resolved_tickets}' not found — no story reads as drafted")
```

with

```python
    resolved_tickets = tickets_dir if tickets_dir is not None else missions_dir.parent / "tickets"
    # Ticket id → (ticked, total) DoR boxes. `rglob`: tickets live at
    # tickets/<mission-id>/<id>.md since 1.6.0 and flat before it; both read.
    drafted: dict[str, tuple[int, int]] = {}
    if resolved_tickets.is_dir():
        for p in sorted(resolved_tickets.rglob("*.md")):
            try:
                ticket_text = unicodedata.normalize("NFC", p.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                notes.append(f"skipped ticket {p}: {exc} — read as draft")
                drafted[p.stem] = (0, 0)
                continue
            drafted[p.stem] = missionnext.dor_counts(ticket_text)
    else:
        notes.append(f"tickets dir '{resolved_tickets}' not found — no story reads as draft or ready")
```

Update the command docstring: `"""Which story next: every backlog story across missions/ as done / ready / draft / to-draft / blocked. Done is derived from the hub's <repo>-svc history (kb svc note rows); ready and draft from the ticket's Definition of Ready checklist. Read-only; exit 0 after a report."""`

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_cli_mission.py -q`
Expected: PASS except `test_docs_name_the_next_command` (README/CHANGELOG — Task 9).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/cli.py tests/test_cli_mission.py
git commit -m "feat: kb mission next reads tickets/<folder>/ and the DoR checklist

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Lint path resolution and coverage accept the folder layout

**Files:**
- Modify: `src/strata_kb/cli.py:2465-2486` (`_resolve_missions_dir`)
- Modify: `src/strata_kb/missionlint.py:303-325` (`check_coverage`)
- Test: `tests/test_missionlint.py`, `tests/test_cli_mission.py`

**Interfaces:**
- Produces: `missionlint.check_coverage(us_ids, tickets_dir)` unchanged signature; a story counts as drafted when `tickets_dir/<mission-id>/<us>.md` or `tickets_dir/<us>.md` exists, where `<mission-id>` is `<us>` with its trailing `-US<n>` removed.
- Produces: `cli._resolve_missions_dir(missions_dir, path)` binds `missions/` next to the nearest ancestor of `path` named `tickets`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_missionlint.py`:

```python
def test_coverage_finds_a_ticket_in_its_mission_folder(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    tickets = tmp_path / "tickets"
    (tickets / MISSION_ID).mkdir(parents=True)
    (tickets / MISSION_ID / f"{MISSION_ID}-US1.md").write_text("x", encoding="utf-8")
    (tickets / f"{MISSION_ID}-US2.md").write_text("x", encoding="utf-8")

    report = missionlint.lint(
        _build_mission(golden_block), _hub(fed_hub), tickets_dir=tickets
    )

    assert not any("US drafted" in msg for msg in _warnings(report))
```

Append to `tests/test_cli_mission.py`:

```python
def test_resolve_missions_dir_from_a_nested_ticket(tmp_path):
    from strata_kb.cli import _resolve_missions_dir

    (tmp_path / "missions").mkdir()
    nested = tmp_path / "tickets" / "M-platform" / "M-platform-US1.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("# t\n", encoding="utf-8")
    assert _resolve_missions_dir(None, nested) == tmp_path / "missions"
    flat = tmp_path / "tickets" / "M-platform-US1.md"
    assert _resolve_missions_dir(None, flat) == tmp_path / "missions"
    assert _resolve_missions_dir(None, tmp_path / "elsewhere" / "x.md") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_missionlint.py::test_coverage_finds_a_ticket_in_its_mission_folder tests/test_cli_mission.py::test_resolve_missions_dir_from_a_nested_ticket -q`
Expected: FAIL — coverage warns `1/2 US drafted`; `_resolve_missions_dir(None, nested)` is None.

- [ ] **Step 3: Implement**

`src/strata_kb/missionlint.py` — replace the `missing = [...]` comprehension in `check_coverage` with:

```python
    missing = [us_id for us_id in us_ids if not _ticket_file_exists(tickets_dir, us_id)]
```

and add above `check_coverage`:

```python
_US_SUFFIX_RE = re.compile(r"-US\d+$")


def _ticket_file_exists(tickets_dir: Path, us_id: str) -> bool:
    """`tickets/<mission-id>/<us>.md` (1.6.0 layout) or `tickets/<us>.md`
    (flat, pre-1.6.0). The mission id is the story id minus `-US<n>`."""
    mission_id = _US_SUFFIX_RE.sub("", us_id)
    return (tickets_dir / mission_id / f"{us_id}.md").is_file() or (
        tickets_dir / f"{us_id}.md"
    ).is_file()
```

Add `import re` to the module imports if missing.

`src/strata_kb/cli.py` — replace the tail of `_resolve_missions_dir`:

```python
    if path is not None:
        for ancestor in (path.parent, *path.parent.parents):
            if ancestor.name == "tickets":
                sibling = ancestor.parent / "missions"
                return sibling if sibling.is_dir() else None
    return None
```

Update its docstring sentence `a ticket at tickets/<id>.md gets its sibling missions/` to `a ticket under tickets/ (flat or tickets/<mission-id>/) gets the missions/ next to that tickets/ directory`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_missionlint.py tests/test_cli_mission.py tests/test_cli_ticket*.py -q`
Expected: PASS (except `test_docs_name_the_next_command`, Task 9).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/cli.py src/strata_kb/missionlint.py tests/test_missionlint.py tests/test_cli_mission.py
git commit -m "feat: mission coverage and ticket lint accept tickets/<mission-id>/ layout

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: Usage transcript cursor reads a nested ticket path

**Files:**
- Modify: `src/strata_kb/usage/transcript.py:36-40`
- Test: `tests/test_usage_transcript.py`

- [ ] **Step 1: Write the failing test**

Append after `test_the_ticket_cursor_is_set_by_a_tickets_path`:

```python
def test_the_ticket_cursor_reads_a_ticket_inside_a_mission_folder(tmp_path: Path):
    path = write_transcript(
        tmp_path,
        [user_row("please read tickets/M-platform/M-platform-US1.md"), usage_row("a1")],
    )

    (row,) = transcript.rows_from_transcript(path, actor="ba")

    assert row.ticket == "M-platform-US1"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_usage_transcript.py::test_the_ticket_cursor_reads_a_ticket_inside_a_mission_folder -q`
Expected: FAIL — `row.ticket == "M-platform"` (the folder matched as the stem) or the row has no ticket.

- [ ] **Step 3: Implement**

Replace `TICKET_PATH_RE`:

```python
# `tickets/<stem>.md` or `tickets/<folder>/<stem>.md` (one folder, the
# mission id, since 1.6.0); missions stay flat.
TICKET_PATH_RE = re.compile(
    rf"(?:tickets{_SEP}(?:[^/\\\"]+?{_SEP})?|missions{_SEP})(?P<stem>[^/\\\"]+?)\.md"
    rf"|docs{_SEP}impl{_SEP}(?P<impl>[^/\\\"]+?)-(?:design|plan)\.md"
)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_usage_transcript.py -q`
Expected: PASS, including the Windows-path test.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/usage/transcript.py tests/test_usage_transcript.py
git commit -m "fix: usage ticket cursor reads tickets/<mission-id>/<id>.md

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: `kb ticket tidy`

**Files:**
- Create: `src/strata_kb/tickettidy.py`
- Modify: `src/strata_kb/cli.py` (new `@ticket_app.command("tidy")` after `ticket_export`)
- Test: `tests/test_cli_ticket_tidy.py` (new)

**Interfaces:**
- Produces: `tickettidy.plan_moves(tickets_dir: Path) -> tuple[list[tuple[Path, Path]], list[Path], list[str]]` — `(moves, unsorted, notes)`; a flat `tickets/*.md` with a valid `> Parent mission: M-x` goes to `tickets/M-x/<name>`; without one it is `unsorted`; an unreadable file is a note.
- Produces: `tickettidy.into_moves(tickets_dir: Path, folder: str, files: list[Path]) -> list[tuple[Path, Path]]`.
- Produces: `tickettidy.apply_moves(moves) -> tuple[list[tuple[Path, Path]], list[str]]` — `(done, conflicts)`; a destination that already exists is a conflict, not an overwrite.
- Produces: CLI `kb ticket tidy [--tickets-dir tickets] [--into <folder>] [FILES...]`, exit 0.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_ticket_tidy.py`:

```python
"""`kb ticket tidy` — flat tickets/*.md into tickets/<mission-id>/."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from strata_kb import tickettidy
from strata_kb.cli import app

runner = CliRunner()

PARENTED = "# Story\n> Parent mission: M-platform\n\n## Summary\nx\n"
ORPHAN = "# Story\n\n## Summary\nx\n"


def _tickets(tmp_path: Path) -> Path:
    d = tmp_path / "tickets"
    d.mkdir()
    (d / "M-platform-US1.md").write_text(PARENTED, encoding="utf-8")
    (d / "M-platform-US2.md").write_text(PARENTED, encoding="utf-8")
    (d / "legacy-login.md").write_text(ORPHAN, encoding="utf-8")
    return d


def test_plan_moves_parented_files_and_lists_orphans(tmp_path):
    d = _tickets(tmp_path)
    moves, unsorted, notes = tickettidy.plan_moves(d)
    assert moves == [
        (d / "M-platform-US1.md", d / "M-platform" / "M-platform-US1.md"),
        (d / "M-platform-US2.md", d / "M-platform" / "M-platform-US2.md"),
    ]
    assert unsorted == [d / "legacy-login.md"]
    assert notes == []


def test_plan_moves_ignores_files_already_in_folders_and_bad_ids(tmp_path):
    d = _tickets(tmp_path)
    (d / "M-platform").mkdir()
    (d / "M-platform" / "M-platform-US3.md").write_text(PARENTED, encoding="utf-8")
    (d / "bad.md").write_text("# S\n> Parent mission: Not_An_Id\n", encoding="utf-8")
    moves, unsorted, _notes = tickettidy.plan_moves(d)
    assert all(src.parent == d for src, _dst in moves)
    assert d / "bad.md" in unsorted


def test_apply_moves_creates_folders_and_refuses_to_overwrite(tmp_path):
    d = _tickets(tmp_path)
    (d / "M-platform").mkdir()
    (d / "M-platform" / "M-platform-US2.md").write_text("other", encoding="utf-8")
    moves, _u, _n = tickettidy.plan_moves(d)
    done, conflicts = tickettidy.apply_moves(moves)
    assert done == [(d / "M-platform-US1.md", d / "M-platform" / "M-platform-US1.md")]
    assert (d / "M-platform" / "M-platform-US1.md").read_text(encoding="utf-8") == PARENTED
    assert (d / "M-platform-US2.md").exists()
    assert conflicts == [f"conflict: {d / 'M-platform' / 'M-platform-US2.md'} already exists — left {d / 'M-platform-US2.md'} in place"]


def test_cli_tidy_moves_reports_and_is_idempotent(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d)])
    assert result.exit_code == 0, result.output
    assert f"moved: {d / 'M-platform-US1.md'} → {d / 'M-platform' / 'M-platform-US1.md'}" in result.output
    assert f"unsorted: {d / 'legacy-login.md'} — pass --into <folder>" in result.output
    again = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d)])
    assert again.exit_code == 0
    assert "moved:" not in again.output
    assert "unsorted:" in again.output


def test_cli_tidy_into_moves_the_named_files(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, [
        "ticket", "tidy", "--tickets-dir", str(d), "--into", "epic-login", str(d / "legacy-login.md"),
    ])
    assert result.exit_code == 0, result.output
    assert (d / "epic-login" / "legacy-login.md").is_file()
    assert "unsorted:" not in result.output


def test_cli_tidy_into_rejects_a_bad_folder_name(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d), "--into", "../x", str(d / "legacy-login.md")])
    assert result.exit_code == 1
    assert "--into" in result.output


def test_cli_tidy_missing_dir_is_a_red_line(tmp_path):
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_cli_ticket_tidy.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'strata_kb.tickettidy'`.

- [ ] **Step 3: Implement the module**

Create `src/strata_kb/tickettidy.py`:

```python
"""`kb ticket tidy` — move flat `tickets/*.md` into `tickets/<mission-id>/`.

Spec 2026-09-29-ticket-status-decision-defaults-design §7. Idempotent: a
file already inside a folder is never touched; a destination that exists
is a conflict, never an overwrite. No git here — the BA commits and git
detects the rename.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb import mission, ticket

FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def plan_moves(tickets_dir: Path) -> tuple[list[tuple[Path, Path]], list[Path], list[str]]:
    """(moves, unsorted, notes) for the flat `*.md` files directly under
    `tickets_dir`. A valid `> Parent mission: M-x` line sends the file to
    `tickets_dir/M-x/<name>`; no line, or a malformed id, is `unsorted`."""
    moves: list[tuple[Path, Path]] = []
    unsorted: list[Path] = []
    notes: list[str] = []
    for path in sorted(tickets_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            notes.append(f"skipped {path}: {exc}")
            continue
        m = ticket.PARENT_MISSION_RE.search(text)
        if m is None or not mission.MISSION_ID_RE.match(m.group(1)):
            unsorted.append(path)
            continue
        moves.append((path, tickets_dir / m.group(1) / path.name))
    return moves, unsorted, notes


def into_moves(tickets_dir: Path, folder: str, files: list[Path]) -> list[tuple[Path, Path]]:
    return [(f, tickets_dir / folder / f.name) for f in files]


def apply_moves(moves: list[tuple[Path, Path]]) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Rename each (src, dst), creating dst's folder. Returns (done,
    conflicts); an existing dst leaves src where it is."""
    done: list[tuple[Path, Path]] = []
    conflicts: list[str] = []
    for src, dst in moves:
        if dst.exists():
            conflicts.append(f"conflict: {dst} already exists — left {src} in place")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        done.append((src, dst))
    return done, conflicts
```

- [ ] **Step 4: Implement the command**

In `src/strata_kb/cli.py`, after `ticket_export` (before `@ticket_app.command("check")`):

```python
@ticket_app.command("tidy")
def ticket_tidy(
    files: list[Path] = typer.Argument(
        None, help="With --into: the flat ticket files to move into that folder"
    ),
    tickets_dir: Path = typer.Option(
        Path("tickets"), "--tickets-dir", help="Where ticket files live"
    ),
    into: str | None = typer.Option(
        None, "--into", help="Folder under tickets/ for FILES that have no parent mission (an epic or feature slug)"
    ),
) -> None:
    """Move flat tickets/*.md into tickets/<mission-id>/ by their
    '> Parent mission:' line; list the rest as 'unsorted'. With --into,
    move the named FILES into tickets/<folder>/ instead. Idempotent, never
    overwrites, no git — commit the renames yourself. Exit 0 after a report."""
    from strata_kb import tickettidy

    if not tickets_dir.is_dir():
        typer.secho(
            f"--tickets-dir '{tickets_dir}' does not exist or is not a directory", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if into is not None:
        if not tickettidy.FOLDER_RE.match(into):
            typer.secho(
                f"--into '{into}' is not a folder name — letters, digits, '.', '_' and '-' only",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if not files:
            typer.secho("--into needs at least one FILE", fg=typer.colors.RED)
            raise typer.Exit(1)
        moves = tickettidy.into_moves(tickets_dir, into, list(files))
        unsorted: list[Path] = []
        notes: list[str] = []
    else:
        moves, unsorted, notes = tickettidy.plan_moves(tickets_dir)
    done, conflicts = tickettidy.apply_moves(moves)
    for n in notes:
        typer.echo(f"note: {n}")
    for src, dst in done:
        typer.echo(f"moved: {src} → {dst}")
    for c in conflicts:
        typer.echo(c)
    for p in unsorted:
        typer.echo(f"unsorted: {p} — pass --into <folder>")
    if not (done or conflicts or unsorted or notes):
        typer.echo("nothing to tidy")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_cli_ticket_tidy.py -q`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/tickettidy.py src/strata_kb/cli.py tests/test_cli_ticket_tidy.py
git commit -m "feat: kb ticket tidy — flat tickets/ into tickets/<mission-id>/

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Wrappers, QUICKSTART, README, CHANGELOG, version

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md`, `claude-command-ba-ticket-author.md`, `cursor-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md`
- Modify: `src/strata_kb/templates/init/mission-template.md:93`
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md:147-150, 166-180`
- Modify: `README.md:274, 688`, `CHANGELOG.md`, `pyproject.toml:3`
- Test: `tests/test_templates.py`, `tests/test_cli_mission.py::test_docs_name_the_next_command`

- [ ] **Step 1: Update the template tests**

In `tests/test_templates.py` replace `test_ba_ticket_wrappers_run_kb_mission_next_at_intake` and `test_ba_ticket_full_wrappers_point_a_drafted_story_at_its_file` with:

```python
def test_ba_ticket_wrappers_run_kb_mission_next_at_intake():
    for name in BA_TICKET_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "run `kb ticket tidy` first" in text, name
        assert "then `kb mission next`" in text, name
        assert "propose the first `to-draft` story" in text, name
        assert "Print every `note:` line of `kb mission next` to the BA verbatim, before the table" in text, name
        assert "A `blocked` story may be drafted only with its reasons acknowledged by the BA" in text, name


def test_ba_ticket_full_wrappers_point_a_draft_or_ready_story_at_its_file():
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        text = _ba_wrapper_text(name)
        assert "A `draft` or `ready` story points at its existing file." in text, name
        assert "A `done: unknown` note means a `draft` or `ready` row may be a merged story — say so." in text, name


def test_ba_ticket_wrappers_save_into_a_mission_or_ba_named_folder():
    for name in BA_TICKET_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "`tickets/<mission-id>/<mission-id>-US<n>.md`" in text, name
        assert "ask the BA for a kebab-case folder name (an epic or feature, e.g. `epic-billing`)" in text, name
        assert "never invent the folder name" in text, name
        assert "for every `unsorted:` line ask the BA for its folder and run `kb ticket tidy --into <folder> <file>`" in text, name


def test_mission_template_allows_a_grounded_on_list():
    text = _read_init_template("mission-template.md")
    assert "A comma-separated list is allowed; the `-code` entry is the one `kb mission next` reads." in text
```

In `tests/test_cli_mission.py::test_docs_name_the_next_command` replace the two README asserts and the two CHANGELOG asserts with:

```python
    assert "| `kb mission next` | Which story next: done / ready / draft / to-draft / blocked across `missions/`, done derived from the hub's `<repo>-svc` history, ready and draft from the ticket's Definition of Ready checklist |" in readme
    assert "`kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]`" in readme
    assert "| `kb ticket tidy [--tickets-dir <dir>] [--into <folder> <file>...]` |" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## 1.6.0") < changelog.index("## 1.5.0")
    assert "`kb mission next`" in changelog
    assert "**Breaking** for scripts reading the JSON `status`" in changelog
    assert "`--kb-dir` is read first when it holds the `-svc` document (a dev machine), the hub second" in readme
    assert "derived from the grounded `-code` document" in changelog
```

In `test_quickstart_ba_documents_which_ticket_next_and_the_bulk_decide` replace the `for word in (...)` line with:

```python
    for word in ("`done`", "`ready`", "`draft`", "`to-draft`", "`blocked`", "Next:", "`kb ticket tidy`"):
```

and add `assert "`drafted`" not in text` after the loop. Keep the `-svc` sentence assert in `test_docs_name_the_next_command` and the 1.4.0 `test_changelog_names_the_ba_side_of_mission_next` untouched — they still hold.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_templates.py -k "ba_ticket or mission_template_allows" tests/test_cli_mission.py::test_docs_name_the_next_command -q`
Expected: FAIL on every new needle.

- [ ] **Step 3: Edit the four ba-ticket-author wrappers**

In each of `claude-skill-ba-ticket-author.md`, `cursor-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md`, replace the Intake sentence block

```
   With no business need given and a `missions/` directory present, run
   `kb mission next` first and show its table: propose the first `ready`
   story; the BA may pick another. A `drafted` story points at its
   existing file. A `blocked` story may be drafted only with its reasons
   acknowledged by the BA — carry those reasons into the handover
   verbatim.
```

with

```
   With no business need given and a `missions/` directory present, run
   `kb ticket tidy` first — it moves any flat `tickets/*.md` into
   `tickets/<mission-id>/`; for every `unsorted:` line ask the BA for its
   folder and run `kb ticket tidy --into <folder> <file>` — then
   `kb mission next`. Print every `note:` line of `kb mission next` to
   the BA verbatim, before the table; never summarise it away. A
   `done: unknown` note means a `draft` or `ready` row may be a merged
   story — say so. Then show the table: propose the first `to-draft`
   story; the BA may pick another. A `draft` or `ready` story points at
   its existing file. A `blocked` story may be drafted only with its
   reasons acknowledged by the BA — carry those reasons into the handover
   verbatim.
```

In the same three files replace

```
   under the ticket's H1 title. Save the ticket as
   `tickets/<mission-id>-US<n>.md` so the back-link check can find it.
```

with

```
   under the ticket's H1 title. Save the ticket as
   `tickets/<mission-id>/<mission-id>-US<n>.md` so the back-link check can
   find it. With no parent mission, ask the BA for a kebab-case folder
   name (an epic or feature, e.g. `epic-billing`) and save
   `tickets/<folder>/<ticket-id>.md` — never invent the folder name.
```

In the same three files replace every remaining `tickets/<ticket-id>.md` with `tickets/<folder>/<ticket-id>.md` (steps 7 and 9, the export command line, and the cursor/copilot front-matter `description` and intro line).

In `claude-command-ba-ticket-author.md` replace line 9 `present, run `kb mission next` first and propose the first `ready` story.` with:

```
present, run `kb ticket tidy` first (then `kb mission next`), print every
`note:` line of `kb mission next` to the BA verbatim, before the table,
and propose the first `to-draft` story; for every `unsorted:` line ask the
BA for its folder and run `kb ticket tidy --into <folder> <file>`. A
`blocked` story may be drafted only with its reasons acknowledged by the BA.
```

and line 14 `to `tickets/<ticket-id>.md` — or `tickets/<mission-id>-US<n>.md`` with `to `tickets/<folder>/<ticket-id>.md` — `tickets/<mission-id>/<mission-id>-US<n>.md` under a parent mission; otherwise ask the BA for a kebab-case folder name (an epic or feature, e.g. `epic-billing`) and never invent the folder name`. Keep the rest of that sentence.

- [ ] **Step 4: Mission template, QUICKSTART, README, CHANGELOG, version**

`mission-template.md` line 93 — append a comment line directly below it:

```
<!-- A comma-separated list is allowed; the `-code` entry is the one `kb mission next` reads. -->
```

`QUICKSTART-ba.md`:
- Replace `` `tickets/M-<slug>-US<n>.md` and carry a `` with `` `tickets/M-<slug>/M-<slug>-US<n>.md` and carry a ``.
- Replace `is reported as one of four states` with `is reported as one of five states`.
- Replace the state table with:

```
| State | Means |
|---|---|
| `done` | the ticket id is in a `hist.*` row of the hub's `-svc` document — the Dev ran `kb svc note` at handover and CI published it on merge |
| `ready` | the ticket file exists and every `## Definition of Ready` box is ticked — waiting for a Dev |
| `draft` | the ticket file exists and a DoR box is still unticked (`DoR 5/8 ticked`), or it has no DoR section |
| `to-draft` | no ticket yet, every `Depends on` story is `done`, every D-row that `Blocks` it is `DECIDED` |
| `blocked` | the reasons are named: `US <id> not done`, `US <id> unknown`, `D<n> OPEN (owner: <x>)` |
```

- Replace `` `/ba-ticket-author` with no argument runs it first and proposes the first `ready` story. A story whose dependency is only `drafted` stays `blocked`: `` with `` `/ba-ticket-author` with no argument runs `kb ticket tidy`, then this, and proposes the first `to-draft` story. A story whose dependency is only `draft` or `ready` stays `blocked`: ``.
- After the paragraph that begins `The `-svc` document is found from the missions' `Grounded on:` line`, add a paragraph:

```
Tickets live at `tickets/<mission-id>/<ticket-id>.md`; a ticket with no
parent mission goes under a folder you name (an epic or feature slug).
`kb ticket tidy` moves a flat `tickets/` into that layout by each file's
`> Parent mission:` line and lists the rest as `unsorted:` — move those
with `kb ticket tidy --into <folder> <file>`. Every command reads both
layouts.
```

`README.md`:
- Line 274: replace the row with `| `kb mission next` | Which story next: done / ready / draft / to-draft / blocked across `missions/`, done derived from the hub's `<repo>-svc` history, ready and draft from the ticket's Definition of Ready checklist |`.
- After it add `| `kb ticket tidy` | Move flat `tickets/*.md` into `tickets/<mission-id>/` by their parent mission; `--into <folder>` for the rest |`.
- Line 688: in the long row replace `as `done` (its id is in a `hist.*` row of the hub's `-svc` document), `drafted` (`tickets/<us-id>.md` exists), `ready` (no ticket, every `Depends on` done, every D-row that `Blocks` it `DECIDED`) or `blocked` (reasons named)` with `as `done` (its id is in a `hist.*` row of the hub's `-svc` document), `ready` (a ticket file exists under `tickets/` — flat or `tickets/<mission-id>/` — with every `## Definition of Ready` box ticked), `draft` (a ticket file with an unticked box or no DoR section; reason `DoR n/m ticked`), `to-draft` (no ticket, every `Depends on` done, every D-row that `Blocks` it `DECIDED`) or `blocked` (reasons named)`; replace `ends with `Next: <us-id> — <title>`` with `ends with `Next: <us-id> — <title>` naming the first `to-draft` story`; replace `The `-svc` document is derived from the missions' `Grounded on:` line (`<x>-code` → `<x>-svc`, `--repo-id` overrides)` with `The `-svc` document is derived from the missions' `Grounded on:` line (a comma-separated list is read, the `-code` entry wins; `<x>-code` → `<x>-svc`, `--repo-id` overrides)`.
- After that row add:

```
| `kb ticket tidy [--tickets-dir <dir>] [--into <folder> <file>...]` | Move each flat `tickets/*.md` whose `> Parent mission: M-x` line is valid to `tickets/M-x/<name>`; print `moved:` per file, `conflict:` when the destination exists (nothing is overwritten), `unsorted:` for a file without a parent mission. With `--into`, move the named files into `tickets/<folder>/` instead. Idempotent; no git — commit the renames yourself | `0` after a report; `1` for a bad `--tickets-dir`, a bad `--into` name, or `--into` without files |
```

`CHANGELOG.md` — insert above `## 1.5.0 — 2026-09-29`:

```
## 1.6.0 — 2026-09-29

- `kb mission next` reports five states: `done` (hub `hist.*` row), `ready` (ticket file with every `## Definition of Ready` box ticked), `draft` (ticket file with an unticked box — reason `DoR n/m ticked` — or no DoR section), `to-draft` (no ticket, dependencies done, D-rows DECIDED) and `blocked`. `Next:` names the first `to-draft` story. **Breaking** for scripts reading the JSON `status`: `drafted` is gone, `ready` changed meaning, `draft` and `to-draft` are new.
- `kb mission next` reads a comma-separated `Grounded on:` line (`<x>-code @ <rev>, <x>-svc @ <rev>`, as `sa-ticket-ground` writes it) and derives the `-svc` document from the `-code` entry — a mission grounded that way used to read `done: unknown (no repo id)` and every merged story as `drafted`. `kb mission lint` warns when no `Grounded on:` line parses.
- Tickets live at `tickets/<mission-id>/<ticket-id>.md`. New `kb ticket tidy` moves a flat `tickets/` into that layout by each file's `> Parent mission:` line (`--into <folder>` for the rest); `kb mission next`, `kb mission lint` coverage, `kb ticket lint` and the usage ledger read both layouts.
- `kb ticket lint`: an NFR `Target` of `N/A — <reason>` passes — the KB holds no number for that concern; a bare `N/A` or a mood still fails.
- BA repos: `ba-ticket-author` runs `kb ticket tidy` at Intake, prints every `note:` line of `kb mission next` verbatim, proposes the first `to-draft` story and saves into the mission folder (or a BA-named one). `QUICKSTART-ba.md` updated. Re-run `kb init --kind ba` to pick up the new text.
```

`pyproject.toml` line 3: `version = "1.6.0"`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all PASS. Then `kb init` template rendering tests (`tests/test_init.py`) still pass — they render the same files.

- [ ] **Step 6: Smoke test on the MyFlix BA repo (read-only)**

Run from the repo root:

```bash
uv run kb mission next --missions-dir /Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix-ba/missions --kb-dir /Users/vuonglq01685/Documents/Projects/MyFlix/code/myflix-ba/.kb
```

Expected: no `done: unknown` note; `| M-platform-operations-US1 | M-platform-operations | done |  |`; the other two tickets `draft` or `ready` with a `DoR n/m ticked` reason. Do not run `kb ticket tidy` there — the BA runs it.

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/templates/init README.md CHANGELOG.md pyproject.toml tests/test_templates.py tests/test_cli_mission.py
git commit -m "docs: ba-ticket-author prints mission-next notes, tidies tickets/, saves into folders — 1.6.0

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review

- Spec §3 → Tasks 4, 5. §4 → Tasks 1, 2, 9 (template sentence, Intake note). §6 lint line → Task 3 (rubric/template wording is PR2). §7 → Tasks 5, 6, 7, 8, 9. §9 tests → each task. §10 out of scope respected: no lint re-run, no `in-progress`, no lint error on flat files.
- `statuses(missions, drafted: dict[str, tuple[int,int]], done)` used identically in Tasks 4 and 5. `dor_counts` defined in Task 4, consumed in Task 5. `grounded_entries` defined in Task 1, consumed in Tasks 1 and 2. `tickettidy.plan_moves / into_moves / apply_moves / FOLDER_RE` defined and consumed in Task 8.
- Test needles in Task 9 Step 1 match the prose written in Steps 3–4 word for word (`_ba_wrapper_text` normalises whitespace, so line wraps do not matter).
