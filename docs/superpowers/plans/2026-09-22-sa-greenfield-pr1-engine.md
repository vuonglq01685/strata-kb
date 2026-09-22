# SA greenfield grounding — PR 1 (engine + CLI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb ticket check` verifies `[NEW: D<n>]` against the parent mission's `## Technology decisions` table (row exists, `Status` is `DECIDED`), accepts a mission's `## Services & order` via `--heading`, and resolves the mission file through `--missions-dir` with the same sibling default `kb ticket lint` has.

**Architecture:** `ticketcheck.check` gets one more injected callable, `load_decisions(mission_id) -> DecisionTable | None`, so the engine stays free of filesystem and CLI imports (same split as `load_doc`). A single `_judge_new` helper replaces the two copies of the `[NEW]` branch in `_check_ids` and `_check_files`. `cli.py` extracts the `--missions-dir` sibling resolution out of `ticket_lint` into a helper both commands call.

**Tech Stack:** Python 3.11+, typer, pytest (`uv run pytest`). Spec: `docs/superpowers/specs/2026-09-22-sa-greenfield-grounding-design.md` §6.

## Global Constraints

- No version bump: `pyproject.toml` `version` and `uv.lock` untouched. CHANGELOG entry under `## Unreleased`.
- No new dependency. `mdutils.py` frozen. No CLI/MCP imports in `ticketcheck.py`.
- CLAUDE.md: run `impact({target: "<symbol>", direction: "upstream"})` before editing `check`, `_check_ids`, `_check_files`, `_check_service_present`, `ticket_lint`, `ticket_check`; run `detect_changes()` before each commit. If the GitNexus index is stale, run `npx gitnexus analyze` first. If the MCP server is down, say so in the commit body and continue.
- Exit codes and the `Grounding: PASS/FAIL` line are unchanged. Every error message ends with `(line N)` naming the ticket line.
- Commit format: `<type>: <description>` (feat/fix/refactor/docs/test/chore). Attribution trailer per session reminder.
- Existing tests are the behavioural pin: `uv run pytest -q` must stay green after every task.

---

## File structure

| File | Change |
|---|---|
| `src/strata_kb/ticketcheck.py` | `Decision`, `DecisionTable`, `LoadDecisions`, `parse_decisions`, `SERVICES_HEADING`, `DECISION_REF_RE`; `check(..., load_decisions=None)`; `_judge_new`; `_check_service_present` skips the mission heading |
| `src/strata_kb/cli.py` | `_resolve_missions_dir` helper (extracted from `ticket_lint`); `ticket_check` gains `--missions-dir`, `--heading`, builds `load_decisions` |
| `tests/test_ticketcheck.py` | mission fixture text, `ticket(parent=)`, `run(heading=, load_decisions=)`; new cases |
| `tests/test_cli_ticket_check.py` | sibling default, explicit `--missions-dir`, bad `--missions-dir`, `--heading`; README pin updated |
| `README.md` | command-table row for `kb ticket check` |
| `CHANGELOG.md` | `## Unreleased` entry |

---

### Task 1: Decision table parsing and `[NEW: D<n>]` verification in the engine

**Files:**
- Modify: `src/strata_kb/ticketcheck.py`
- Test: `tests/test_ticketcheck.py`

**Interfaces:**
- Produces:
  - `ticketcheck.Decision(id: str, status: str, owner: str)` — frozen dataclass
  - `ticketcheck.DecisionTable(source: str, rows: dict[str, Decision])` — frozen dataclass
  - `ticketcheck.LoadDecisions = Callable[[str], DecisionTable | None]` — mission id → table, `None` when the mission file does not exist
  - `ticketcheck.parse_decisions(text: str, source: str) -> DecisionTable` — parses `## Technology decisions` of `text`; empty `rows` when the section or its `#`/`Status` columns are missing
  - `ticketcheck.check(text, *, load_doc, heading=HEADING, load_decisions: LoadDecisions | None = None)`
  - `ticketcheck.DECISION_REF_RE` — `^D\d+$`

- [ ] **Step 1: Extend the test helpers**

In `tests/test_ticketcheck.py`, replace the `ticket` and `run` helpers (keep `grounding`, `errors`, `warnings`, `notes` as they are) and add the mission fixture text:

```python
MISSION = """# Billing — mission
> Mission: M-demo

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.billing — charges per flight plan | DECIDED | tech-lead | M-demo-US1 |
| D2 | New db.invoice table | OPEN | Alice | M-demo-US1 |
"""


def decisions_of(mission_text: str | None):
    """A `load_decisions` over one in-memory mission; `None` = file missing."""
    def load(mission_id: str):
        if mission_text is None:
            return None
        return ticketcheck.parse_decisions(mission_text, f"missions/{mission_id}.md")
    return load


def ticket(section: str | None, *, parent: str | None = None, heading: str = "## Technical grounding") -> str:
    parts = ["# T-1 — Show airspace"]
    if parent is not None:
        parts.append(f"> Parent mission: {parent}")
    parts += ["", "## Summary", "Something.", ""]
    if section is not None:
        parts += [heading, section, ""]
    parts += ["## Open questions", "- [ ] none", ""]
    return "\n".join(parts)


def run(text: str, kb_dir: Path, *, heading: str = "## Technical grounding", load_decisions=None) -> LintReport:
    def load_doc(repo, doc):
        d = kb_dir / doc
        if not (d / "_manifest.yaml").exists():
            return None
        return ticketcheck.load_doc_dir(d, str(d))

    return ticketcheck.check(text, load_doc=load_doc, heading=heading, load_decisions=load_decisions)
```

- [ ] **Step 2: Run the existing suite to confirm the helpers are backward compatible**

Run: `uv run pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: FAIL only with `TypeError: check() got an unexpected keyword argument 'load_decisions'` (every test goes through `run`). Nothing else may fail.

- [ ] **Step 3: Write the failing tests for decision references**

Append to `tests/test_ticketcheck.py`:

```python
# --- Task 1 (greenfield): [NEW: D<n>] against the parent mission ----------


def test_parse_decisions_reads_id_status_owner_by_header_name():
    table = ticketcheck.parse_decisions(MISSION, "missions/M-demo.md")
    assert table.source == "missions/M-demo.md"
    assert table.rows["D1"] == ticketcheck.Decision("D1", "DECIDED", "tech-lead")
    assert table.rows["D2"].status == "OPEN"


def test_parse_decisions_survives_a_reordered_table():
    text = (
        "## Technology decisions\n"
        "| Status | Owner | # | Decision |\n"
        "|---|---|---|---|\n"
        "| decided | Bob | D7 | whatever |\n"
    )
    table = ticketcheck.parse_decisions(text, "x")
    assert table.rows == {"D7": ticketcheck.Decision("D7", "decided", "Bob")}


def test_parse_decisions_without_the_section_is_empty():
    assert ticketcheck.parse_decisions("# nothing here\n", "x").rows == {}


def test_decided_reference_passes_with_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Service="svc.billing [NEW: D1]", Files=["src/billing/ [NEW: D1]"]),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert errors(report) == [], report.render("Grounding")
    assert any("new: svc.billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report))
    assert any("new: src/billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report))


def test_open_decision_reference_is_an_error_naming_the_owner(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Tables="db.invoice [NEW: D2]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert report.passed is False
    assert any("decision D2 is OPEN (owner: Alice)" in e for e in errors(report))


def test_missing_decision_row_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D9]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any("decision D9 not in missions/M-demo.md's Technology decisions" in e for e in errors(report))


def test_decision_reference_without_a_parent_mission_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"))
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any("[NEW: D1] needs a parent mission" in e for e in errors(report))
    # Externals is the 8th grounding line; the section heading sits on line 6.
    assert "(line 13)" in [e for e in errors(report) if "D1" in e][0]


def test_decision_reference_with_a_missing_mission_file_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"), parent="M-gone")
    report = run(text, kb_dir, load_decisions=decisions_of(None))
    assert any("parent mission 'M-gone' not found" in e for e in errors(report))


def test_decision_reference_with_no_loader_is_treated_as_not_found(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"), parent="M-demo")
    report = run(text, kb_dir)  # load_decisions=None: caller supplied no missions dir
    assert any("parent mission 'M-demo' not found" in e for e in errors(report))


def test_free_text_new_with_a_decisions_table_present_warns(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives later]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert report.passed is True
    assert any("reference the row as [NEW: D<n>]" in w for w in warnings(report))


def test_free_text_new_without_a_parent_mission_stays_a_plain_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives later]"))
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("[NEW: D<n>]" in w for w in warnings(report))
    assert any("new: int.stripe — billing arrives later" in n for n in notes(report))
```

- [ ] **Step 4: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_ticketcheck.py -q -k "decision or parse_decisions or free_text"`
Expected: FAIL — `AttributeError: module 'strata_kb.ticketcheck' has no attribute 'parse_decisions'` / `TypeError` on `load_decisions`.

- [ ] **Step 5: Implement the decision table and `_judge_new`**

In `src/strata_kb/ticketcheck.py`:

Add after the `from strata_kb.mdutils import slice_section` import:

```python
from strata_kb import mission, ticket
```

Add after `TREE_DEPTH = 4 …`:

```python
SERVICES_HEADING = "## Services & order"
DECISION_REF_RE = re.compile(r"^D\d+$")
```

Add after the `LoadDoc = …` alias:

```python
@dataclass(frozen=True)
class Decision:
    id: str
    status: str
    owner: str


@dataclass(frozen=True)
class DecisionTable:
    source: str  # human label, e.g. "missions/M-demo.md" or "this mission"
    rows: dict[str, Decision]


LoadDecisions = Callable[[str], DecisionTable | None]  # mission id -> table, None = file missing


def parse_decisions(text: str, source: str) -> DecisionTable:
    """The `## Technology decisions` table of `text` keyed by its `#` cell.
    Columns are found by header name, so a reordered table still parses;
    no section or no `#`/`Status` header -> empty rows."""
    body = lintcore.section_body(text, mission.TECH_DECISIONS_HEADING)
    rows = lintcore.table_rows(body) if body is not None else []
    if not rows:
        return DecisionTable(source, {})
    header = [c.strip().lower() for c in rows[0]]
    i_id = header.index("#") if "#" in header else None
    i_status = header.index("status") if "status" in header else None
    i_owner = header.index("owner") if "owner" in header else None
    if i_id is None or i_status is None:
        return DecisionTable(source, {})
    out: dict[str, Decision] = {}
    for r in rows[1:]:
        if len(r) <= max(i_id, i_status):
            continue
        owner = r[i_owner].strip() if i_owner is not None and len(r) > i_owner else ""
        out[r[i_id].strip()] = Decision(r[i_id].strip(), r[i_status].strip(), owner)
    return DecisionTable(source, out)
```

Add after `_parse_section`:

```python
@dataclass(frozen=True)
class _Decisions:
    table: DecisionTable | None
    mission_id: str | None  # the `> Parent mission:` id, or None


def _resolve_decisions(text: str, heading: str, load_decisions: LoadDecisions | None) -> _Decisions:
    """Mission heading: the table is in the checked text itself. Ticket
    heading: via the back-link; `table is None` with a `mission_id` means
    the mission file could not be loaded."""
    if heading == SERVICES_HEADING:
        return _Decisions(parse_decisions(text, "this mission"), None)
    m = ticket.PARENT_MISSION_RE.search(text)
    if m is None:
        return _Decisions(None, None)
    mission_id = m.group(1)
    table = load_decisions(mission_id) if load_decisions is not None else None
    return _Decisions(table, mission_id)


def _judge_new(label: str, new: re.Match, lineno: int, decisions: _Decisions,
               issues: list[Issue], notes: list[str]) -> None:
    """One `[NEW: …]` marker: free text -> note; `D<n>` -> verified against
    the decisions table. `label` is the id or path the marker exempts."""
    reason = (new.group("reason") or "").strip()
    if not reason:
        issues.append(Issue("warning", f"[NEW] without a reason for {label} (line {lineno})"))
        return
    if not DECISION_REF_RE.match(reason):
        notes.append(f"new: {label} — {reason} (line {lineno})")
        if decisions.table is not None and decisions.table.rows:
            issues.append(
                Issue("warning", f"{decisions.table.source} has Technology decisions — reference the row as [NEW: D<n>] (line {lineno})")
            )
        return
    if decisions.table is None:
        if decisions.mission_id is None:
            issues.append(
                Issue("error", f"[NEW: {reason}] needs a parent mission to hold the decision — add `> Parent mission: M-<slug>` under the title, or write [NEW: <reason>] (line {lineno})")
            )
        else:
            issues.append(
                Issue("error", f"parent mission '{decisions.mission_id}' not found under missions/ — pass --missions-dir, or write [NEW: <reason>] (line {lineno})")
            )
        return
    row = decisions.table.rows.get(reason)
    if row is None:
        issues.append(
            Issue("error", f"decision {reason} not in {decisions.table.source}'s Technology decisions — append the row there first (line {lineno})")
        )
        return
    if row.status.upper() != "DECIDED":
        issues.append(
            Issue("error", f"decision {reason} is {row.status} (owner: {row.owner or 'none'}) — a human decides before Dev (line {lineno})")
        )
        return
    notes.append(f"new: {label} — {reason} (DECIDED, owner {row.owner or 'none'}) (line {lineno})")
```

Change `check`:

```python
def check(text: str, *, load_doc: LoadDoc, heading: str = HEADING,
          load_decisions: LoadDecisions | None = None) -> LintReport:
```

and after `notes.append(f"{doc_id} read from {doc.source}")` add:

```python
    decisions = _resolve_decisions(text, heading, load_decisions)
```

then pass it: `_check_ids(section, doc, decisions, issues, notes)` and `_check_files(section, doc, decisions, issues, notes)`.

In `_check_ids`, change the signature to `(section, doc, decisions: _Decisions, issues, notes)` and replace the block

```python
            if new is not None:
                reason = (new.group("reason") or "").strip()
                if reason:
                    notes.append(f"new: {sid} — {reason} (line {lineno})")
                else:
                    issues.append(Issue("warning", f"[NEW] without a reason for {sid} (line {lineno})"))
                continue
```

with

```python
            if new is not None:
                _judge_new(sid, new, lineno, decisions, issues, notes)
                continue
```

In `_check_files`, change the signature to `(section, doc, decisions: _Decisions, issues, notes)` and replace

```python
        if new is not None:
            reason = (new.group("reason") or "").strip()
            if reason:
                notes.append(f"new: {path} — {reason} (line {lineno})")
            else:
                issues.append(Issue("warning", f"[NEW] without a reason for {path} (line {lineno})"))
            continue
```

with

```python
        if new is not None:
            _judge_new(path, new, lineno, decisions, issues, notes)
            continue
```

Note: `_check_ids` emits one `_judge_new` per id on the line, so a line with two `[NEW: D1]`-exempted ids notes twice — same as today's per-id note.

- [ ] **Step 6: Run the engine and CLI suites**

Run: `uv run pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: all PASS (existing `[NEW]` tests still green: free-text notes, empty-reason warning).

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -m "feat(ticketcheck): verify [NEW: D<n>] against the parent mission's Technology decisions"
```

---

### Task 2: `## Services & order` heading — decisions in the same file, no `Service:` warning

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (`_check_service_present`, `check`)
- Test: `tests/test_ticketcheck.py`

**Interfaces:**
- Consumes: `SERVICES_HEADING`, `_resolve_decisions` from Task 1.
- Produces: `check(..., heading=SERVICES_HEADING)` verifies a mission's `## Services & order` with `[NEW: D<n>]` resolved against the mission's own `## Technology decisions`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ticketcheck.py`:

```python
# --- Task 2 (greenfield): mission heading -----------------------------------


def services_and_order(rev: str, second_row: str) -> str:
    return (
        f"- Grounded on: demo:demo-code @ {rev}\n"
        "\n"
        "| Order | Service | Depends on | Why this order |\n"
        "|---|---|---|---|\n"
        "| 1 | svc.airspace-service | — | base |\n"
        f"| 2 | {second_row} | svc.airspace-service | needs airspace |\n"
    )


def mission_with_services(rev: str, second_row: str) -> str:
    return MISSION + "\n## Services & order\n" + services_and_order(rev, second_row) + "\n"


def test_mission_heading_resolves_decisions_from_the_same_file(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.billing [NEW: D1]")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert errors(report) == [], report.render("Grounding")
    assert any("new: svc.billing — D1 (DECIDED" in n for n in notes(report))


def test_mission_heading_open_decision_fails(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.invoicing [NEW: D2]")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert any("decision D2 is OPEN (owner: Alice)" in e for e in errors(report))


def test_mission_heading_does_not_warn_about_a_service_line(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.airspace-service")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert not any("Service:" in w for w in warnings(report))


def test_mission_heading_unknown_service_is_still_an_error(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.nope")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert any("unknown id 'svc.nope'" in e for e in errors(report))
```

- [ ] **Step 2: Run them to verify the failure**

Run: `uv run pytest tests/test_ticketcheck.py -q -k mission_heading`
Expected: `test_mission_heading_does_not_warn_about_a_service_line` FAILS (the `Service:` warning fires); the other three PASS already through Task 1's `_resolve_decisions` — if any of them fails, fix Task 1 before continuing.

- [ ] **Step 3: Skip the `Service:` sanity check for the mission heading**

In `ticketcheck.py` change the call in `check` to `_check_service_present(section, heading, issues)` and the function to:

```python
def _check_service_present(section: _Section, heading: str, issues: list[Issue]) -> None:
    if heading == SERVICES_HEADING:
        return  # the mission table has no `- Service:` line by design
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service" and any(
            sid.startswith("svc.") for sid in ID_RE.findall(line)
        ):
            return
    issues.append(Issue("warning", "no `svc.<name>` on the `Service:` line — which service does this ticket touch?"))
```

- [ ] **Step 4: Run the suites**

Run: `uv run pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -m "feat(ticketcheck): check a mission's Services & order against its own Technology decisions"
```

---

### Task 3: Extract `_resolve_missions_dir` from `ticket_lint`

**Files:**
- Modify: `src/strata_kb/cli.py` (`ticket_lint`, around lines 2383–2412)
- Test: `tests/test_cli_ticket.py` (existing tests are the pin — no new test)

**Interfaces:**
- Produces: `cli._resolve_missions_dir(missions_dir: Path | None, path: Path | None) -> Path | None` — explicit non-directory → red line + `typer.Exit(1)`; otherwise the sibling `missions/` of a `tickets/` parent when it is a directory, else `None`.

- [ ] **Step 1: Run the pin before touching anything**

Run: `uv run pytest tests/test_cli_ticket.py -q`
Expected: PASS (record the count).

- [ ] **Step 2: Add the helper above `ticket_lint`**

Insert directly before `@ticket_app.command("lint")`:

```python
def _resolve_missions_dir(missions_dir: Path | None, path: Path | None) -> Path | None:
    """Where mission files live for a ticket command. An explicit
    --missions-dir that is not a directory is a BA typo and a hard error —
    otherwise the engine's .is_file() probing would misreport a real mission
    as missing. The default is fail-soft: a ticket at tickets/<id>.md gets
    its sibling missions/ when that exists, else None (the engine notes the
    skipped checks). Gated on the parent's name so an unrelated missions/
    next to some other file never binds."""
    if missions_dir is not None:
        if not missions_dir.is_dir():
            typer.secho(
                f"--missions-dir '{missions_dir}' does not exist or is not a directory",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        return missions_dir
    if path is not None and path.parent.name == "tickets":
        sibling = path.parent.parent / "missions"
        if sibling.is_dir():
            return sibling
    return None
```

- [ ] **Step 3: Replace the inline block in `ticket_lint`**

Delete from the comment `# An explicitly-passed --missions-dir is a deliberate BA choice…` through the `if sibling.is_dir(): resolved_missions = sibling` block, and put in its place:

```python
    resolved_missions = _resolve_missions_dir(missions_dir, path)
```

The `handle = _hub_or_exit(hub, kb_dir)` line and the `lint(...)` call stay as they are (`missions_dir=resolved_missions`).

- [ ] **Step 4: Run the pin again**

Run: `uv run pytest tests/test_cli_ticket.py tests/test_cli_mission.py -q`
Expected: same PASS count as Step 1. `test_explicit_missions_dir_overrides_the_sibling` and the bad-dir test are the ones that would catch a regression.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/cli.py
git commit -m "refactor(cli): extract the ticket-lint missions-dir resolution into a helper"
```

---

### Task 4: `kb ticket check --missions-dir --heading`, README row, CHANGELOG

**Files:**
- Modify: `src/strata_kb/cli.py` (`ticket_check`)
- Modify: `README.md` (command table row for `kb ticket check`, line ~685)
- Modify: `CHANGELOG.md`
- Test: `tests/test_cli_ticket_check.py`

**Interfaces:**
- Consumes: `_resolve_missions_dir` (Task 3); `ticketcheck.parse_decisions`, `ticketcheck.LoadDecisions`, `ticketcheck.SERVICES_HEADING` (Tasks 1–2).
- Produces: CLI `kb ticket check <file|-> [--kb-dir] [--hub] [--json] [--missions-dir DIR] [--heading H2]`.

- [ ] **Step 1: Write the failing CLI tests**

Append to `tests/test_cli_ticket_check.py` (imports already include `Path`, `runner`, `app`, `grounding`, `ticket`; add `from tests.test_ticketcheck import MISSION, mission_with_services` to the existing import line):

```python
def _layout(tmp_path: Path, rev: str, section_kwargs: dict, *, parent: str | None = "M-demo") -> Path:
    """tickets/t.md next to missions/M-demo.md — the layout kb init scaffolds."""
    (tmp_path / "tickets").mkdir()
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "tickets" / "t.md"
    path.write_text(ticket(grounding(rev, **section_kwargs), parent=parent), encoding="utf-8")
    return path


def test_sibling_missions_dir_is_the_default(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = _layout(tmp_path, rev, {"Service": "svc.billing [NEW: D1]"})
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
    assert "[note] new: svc.billing — D1 (DECIDED, owner tech-lead)" in result.output


def test_no_sibling_default_outside_a_tickets_directory(code_doc, tmp_path):
    kb_dir, rev = code_doc
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, Service="svc.billing [NEW: D1]"), parent="M-demo"), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "parent mission 'M-demo' not found" in result.output


def test_explicit_missions_dir(code_doc, tmp_path):
    kb_dir, rev = code_doc
    elsewhere = tmp_path / "plans"
    elsewhere.mkdir()
    (elsewhere / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, Service="svc.billing [NEW: D1]"), parent="M-demo"), encoding="utf-8")
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--missions-dir", str(elsewhere)]
    )
    assert result.exit_code == 0, result.output


def test_bad_explicit_missions_dir_is_a_red_line(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--missions-dir", str(tmp_path / "nope")]
    )
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output


def test_open_decision_reference_exits_1(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = _layout(tmp_path, rev, {"Tables": "db.invoice [NEW: D2]"})
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "[error] decision D2 is OPEN (owner: Alice)" in result.output


def test_heading_services_and_order(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "M-demo.md"
    path.write_text(mission_with_services(rev, "svc.billing [NEW: D1]"), encoding="utf-8")
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--heading", "## Services & order"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("Grounding: PASS")
```

And update the README pin in `test_docs_name_the_check_command` to the new row text:

```python
    assert "`kb ticket check <file\\|-> [--kb-dir <dir>] [--hub <url>] [--json] [--missions-dir <dir>] [--heading <h2>]`" in readme
```

- [ ] **Step 2: Run them to verify the failure**

Run: `uv run pytest tests/test_cli_ticket_check.py -q`
Expected: the six new tests FAIL (`No such option: --missions-dir` / `--heading`, or exit 1 on the sibling case); `test_docs_name_the_check_command` FAILS on the README string.

- [ ] **Step 3: Extend `ticket_check`**

In `src/strata_kb/cli.py`, add two options to `ticket_check`'s signature after `hub`:

```python
    missions_dir: Path | None = typer.Option(
        None,
        "--missions-dir",
        help="Where mission files live, for `[NEW: D<n>]` references to the "
        "parent mission's Technology decisions (default: the ticket file's "
        "sibling 'missions/' directory)",
    ),
    heading: str = typer.Option(
        "## Technical grounding",
        "--heading",
        help="Section to check: `## Technical grounding` (ticket) or "
        "`## Services & order` (mission plan; decisions are read from the "
        "same file)",
    ),
```

Track the path like `ticket_lint` does — change the read block to:

```python
    path: Path | None = None
    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    resolved_missions = _resolve_missions_dir(missions_dir, path)
```

After the existing `load_doc` closure add:

```python
    def load_decisions(mission_id: str) -> ticketcheck.DecisionTable | None:
        if resolved_missions is None:
            return None
        mission_path = resolved_missions / f"{mission_id}.md"
        try:
            mission_text = mission_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return ticketcheck.parse_decisions(mission_text, str(mission_path))
```

and change the call to:

```python
    report = ticketcheck.check(
        text, load_doc=load_doc, heading=heading, load_decisions=load_decisions
    )
```

Update the docstring's first line to: `"""SA grounding gate: every id in '## Technical grounding' exists in the -code document, columns/routes/commands/files match it, `[NEW: D<n>]` points at a DECIDED row of the parent mission's Technology decisions, and Open decisions is empty. Exit 0 PASS, 1 FAIL."""`

- [ ] **Step 4: Update the README row**

In `README.md`, replace the `kb ticket check` row of the command table with:

```markdown
| `kb ticket check <file\|-> [--kb-dir <dir>] [--hub <url>] [--json] [--missions-dir <dir>] [--heading <h2>]` | SA grounding gate: every `svc.* / db.* / api.* / int.* / cmd.*` id in `## Technical grounding` exists in the `<repo>-code` document (local `--kb-dir` first, hub federation second), `Grounded on:` matches the document's revision, columns / routes / commands match its tables, `Files:` are in `struct.tree`, every `[NEW: D<n>]` names a `DECIDED` row of the parent mission's `## Technology decisions` (`--missions-dir`, default the sibling `missions/`), and `Open decisions` is empty. `--heading "## Services & order"` checks a mission plan's SA section against its own decisions table | `0` PASS, `1` FAIL |
```

- [ ] **Step 5: Add the CHANGELOG entry**

At the top of `CHANGELOG.md`, directly above `## 1.1.0 — 2026-09-21`, insert:

```markdown
## Unreleased

- `kb ticket check` verifies `[NEW: D<n>]` markers against the parent mission's `## Technology decisions`: the row must exist and be `DECIDED` (an `OPEN` row fails, naming its owner). Greenfield tickets ground code that does not exist yet through a decided design row instead of parking it under `Open decisions`. New `--missions-dir` (default: the sibling `missions/`, as `kb ticket lint`) and `--heading "## Services & order"` to check a mission plan's SA section against its own table.

```

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: all PASS, including `tests/test_readme.py` (the exit-code pin lists producers of exit 2 — this command still adds none).

- [ ] **Step 7: Run `detect_changes()` and commit**

Run `detect_changes()` via the GitNexus MCP (or `npx gitnexus detect-changes` from the project root if the MCP is down); confirm only `ticketcheck.*`, `cli.ticket_check`, `cli.ticket_lint`, `cli._resolve_missions_dir` and their tests are listed.

```bash
git add src/strata_kb/cli.py tests/test_cli_ticket_check.py README.md CHANGELOG.md
git commit -m "feat(cli): kb ticket check --missions-dir and --heading for greenfield grounding"
```

---

## Self-review against spec §6

- §6.1 CLI options and the `ticket_lint`-shared sibling default → Tasks 3, 4.
- §6.2 `decisions` callable, header-name column lookup, the five-row outcome table (no back-link / missing file / missing row / OPEN / DECIDED), free-text warning when a table is present, empty-reason warning unchanged, exit codes unchanged → Tasks 1, 2 (mission heading reads the same text).
- §6.3 tests: engine cases incl. reordered table and `Files:` entries (Task 1), mission heading (Task 2), CLI sibling / explicit / none-elsewhere / `--heading` (Task 4), `ticket lint` behaviour pinned by existing tests (Task 3), README row + pin (Task 4). Template/wrapper needles belong to PR 2.
- Deviation from the spec, deliberate: "no `## Technology decisions` section in the mission" is reported as `decision D<n> not in <file>'s Technology decisions` rather than a distinct message — the row is missing either way and the fix is the same (append it). `_check_service_present` skipping the mission heading was not in the spec; without it every mission check carries a spurious warning.
