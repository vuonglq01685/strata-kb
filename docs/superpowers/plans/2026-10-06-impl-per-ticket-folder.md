# docs/impl per-ticket folder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move a dev repo's ticket work from flat `docs/impl/<id>-*` into `docs/impl/<id>/`, and restructure existing repos automatically on upgrade.

**Architecture:** New `impltidy.py` plans the moves and reuses `tickettidy.apply_moves` to run them (no git, never overwrite). `kb impl tidy`, `kb init --kind dev`, and the `dev-implement-ticket` Intake step all call it. Readers (`prlint`, usage transcript regex) read the new layout only; wrappers and docs get a mechanical path rewrite.

**Tech Stack:** Python 3, typer, pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-impl-per-ticket-folder-design.md`

## Global Constraints

- New layout: `docs/impl/<ticket-id>/{design.md, plan.md, context.md, review/}`.
- Tidy never overwrites, never commits, never calls git; idempotent.
- Readers read the new layout only — no dual-layout fallback.
- No version bump (pyproject / uv.lock untouched); CHANGELOG under `## Unreleased`.
- Commit messages via `git commit -F <file>` (not heredoc `-m`).
- Test command: `uv run pytest -q`.

---

### Task 1: `impltidy` core

**Files:**
- Create: `src/strata_kb/impltidy.py`
- Test: `tests/test_impltidy.py`

**Interfaces:**
- Consumes: `strata_kb.tickettidy.apply_moves(moves: list[tuple[Path, Path]]) -> tuple[list[tuple[Path, Path]], list[str]]` (done, conflicts).
- Produces: `impltidy.plan_moves(impl_dir: Path) -> list[tuple[Path, Path]]`; `impltidy.tidy(impl_dir: Path) -> tuple[list[tuple[Path, Path]], list[str]]` (done, conflicts; `([], [])` when `impl_dir` is not a directory).

Depends on: none

- [ ] **Step 1: Write the failing test** — `tests/test_impltidy.py`:

```python
from pathlib import Path

from strata_kb import impltidy


def _flat(d: Path) -> None:
    d.mkdir(parents=True)
    (d / "ABC-12-design.md").write_text("d", encoding="utf-8")
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    (d / "ABC-12-context.md").write_text("c", encoding="utf-8")
    (d / "ABC-12-review").mkdir()
    (d / "ABC-12-review" / "branch.diff").write_text("x", encoding="utf-8")
    (d / "M-stock-US2-plan.md").write_text("p2", encoding="utf-8")


def test_tidy_moves_every_flat_kind_into_the_ticket_folder(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    _flat(d)
    done, conflicts = impltidy.tidy(d)
    assert conflicts == []
    assert len(done) == 5
    assert (d / "ABC-12" / "design.md").read_text(encoding="utf-8") == "d"
    assert (d / "ABC-12" / "plan.md").read_text(encoding="utf-8") == "p"
    assert (d / "ABC-12" / "context.md").read_text(encoding="utf-8") == "c"
    assert (d / "ABC-12" / "review" / "branch.diff").read_text(encoding="utf-8") == "x"
    assert (d / "M-stock-US2" / "plan.md").read_text(encoding="utf-8") == "p2"
    assert not (d / "ABC-12-design.md").exists()
    assert not (d / "ABC-12-review").exists()


def test_tidy_is_idempotent(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    _flat(d)
    impltidy.tidy(d)
    assert impltidy.tidy(d) == ([], [])


def test_existing_destination_is_a_conflict_and_keeps_the_source(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ABC-12-plan.md").write_text("old", encoding="utf-8")
    (d / "ABC-12").mkdir()
    (d / "ABC-12" / "plan.md").write_text("new", encoding="utf-8")
    done, conflicts = impltidy.tidy(d)
    assert done == []
    assert len(conflicts) == 1 and "ABC-12-plan.md" in conflicts[0]
    assert (d / "ABC-12-plan.md").read_text(encoding="utf-8") == "old"
    assert (d / "ABC-12" / "plan.md").read_text(encoding="utf-8") == "new"


def test_unrelated_entries_are_left_alone(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    for name in (".gitkeep", ".gitignore", "notes.md", "ABC-12-notes.md"):
        (d / name).write_text("", encoding="utf-8")
    (d / "ABC-9").mkdir()
    (d / "ABC-9" / "plan.md").write_text("", encoding="utf-8")
    assert impltidy.plan_moves(d) == []


def test_missing_impl_dir_is_nothing_to_do(tmp_path: Path):
    assert impltidy.tidy(tmp_path / "nowhere") == ([], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_impltidy.py -q`
Expected: FAIL — `ImportError: cannot import name 'impltidy'`.

- [ ] **Step 3: Write minimal implementation** — `src/strata_kb/impltidy.py`:

```python
"""`kb impl tidy` — move flat `docs/impl/<id>-*` into `docs/impl/<id>/`.

Spec 2026-10-06-impl-per-ticket-folder-design. `<id>-design.md`,
`<id>-plan.md`, `<id>-context.md` become `<id>/design.md` … and the
`<id>-review/` folder becomes `<id>/review/`. Idempotent; an existing
destination is a conflict, never an overwrite. No git — the Dev commits and
git detects the rename.
"""

from __future__ import annotations

import re
from pathlib import Path

from strata_kb.tickettidy import apply_moves

_FILE_RE = re.compile(r"^(?P<id>.+)-(?P<kind>design|plan|context)\.md$")
_REVIEW_RE = re.compile(r"^(?P<id>.+)-review$")


def plan_moves(impl_dir: Path) -> list[tuple[Path, Path]]:
    """(src, dst) for every flat ticket entry directly under `impl_dir`."""
    moves: list[tuple[Path, Path]] = []
    for path in sorted(impl_dir.iterdir()):
        if path.is_file() and (m := _FILE_RE.match(path.name)):
            moves.append((path, impl_dir / m["id"] / f"{m['kind']}.md"))
        elif path.is_dir() and (m := _REVIEW_RE.match(path.name)):
            moves.append((path, impl_dir / m["id"] / "review"))
    return moves


def tidy(impl_dir: Path) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Apply `plan_moves`; (done, conflicts). No `impl_dir` → nothing to do."""
    if not impl_dir.is_dir():
        return [], []
    return apply_moves(plan_moves(impl_dir))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_impltidy.py -q`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/impltidy.py tests/test_impltidy.py
git commit -F <msgfile>   # "feat: impltidy moves flat docs/impl entries into per-ticket folders"
```

---

### Task 2: `kb impl tidy`, `kb init --kind dev` hook, gitignore

**Files:**
- Modify: `src/strata_kb/cli.py` (sub-app block near line 78; new command after `plan waves`)
- Modify: `src/strata_kb/initcmd.py:536-538` (`init_repo`, dev branch)
- Modify: `src/strata_kb/templates/init/impl-gitignore.txt`
- Test: `tests/test_cli_impltidy.py` (create), `tests/test_init.py:1800-1803`, `tests/test_templates.py:2149-2150`

**Interfaces:**
- Consumes: `impltidy.tidy(impl_dir: Path) -> tuple[list[tuple[Path, Path]], list[str]]` (Task 1).
- Produces: CLI `kb impl tidy [--impl-dir PATH]`; `init_repo` dev branch appends `"moved  <src> → <dst>"` to `report.notes` per move and each conflict string to `report.notes`.

Depends on: Task 1

- [ ] **Step 1: Write the failing tests**

`tests/test_cli_impltidy.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app

runner = CliRunner()


def test_impl_tidy_moves_and_reports(tmp_path: Path):
    d = tmp_path / "impl"
    d.mkdir()
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert result.exit_code == 0, result.output
    assert "moved:" in result.output
    assert (d / "ABC-12" / "plan.md").is_file()
    again = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert again.exit_code == 0
    assert "nothing to tidy" in again.output


def test_impl_tidy_reports_conflicts_and_exits_0(tmp_path: Path):
    d = tmp_path / "impl"
    (d / "ABC-12").mkdir(parents=True)
    (d / "ABC-12" / "plan.md").write_text("new", encoding="utf-8")
    (d / "ABC-12-plan.md").write_text("old", encoding="utf-8")
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(d)])
    assert result.exit_code == 0
    assert "conflict:" in result.output


def test_impl_tidy_missing_dir_is_exit_1(tmp_path: Path):
    result = runner.invoke(app, ["impl", "tidy", "--impl-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
```

Append to `tests/test_init.py` (next to `test_init_kind_dev_gitignores_the_context_cache`):

```python
def test_init_kind_dev_tidies_a_flat_docs_impl(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    (d / "ABC-12-review").mkdir()
    report = init_repo(tmp_path, "dev")
    assert (d / "ABC-12" / "plan.md").read_text(encoding="utf-8") == "p"
    assert (d / "ABC-12" / "review").is_dir()
    assert any(n.startswith("moved ") for n in report.notes)


def test_init_kind_ba_leaves_docs_impl_alone(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ABC-12-plan.md").write_text("p", encoding="utf-8")
    init_repo(tmp_path, "ba")
    assert (d / "ABC-12-plan.md").is_file()
```

Extend `test_init_kind_dev_gitignores_the_context_cache` (test_init.py:1803) with:

```python
    assert "*/context.md" in gi
    assert "*/review/" in gi
```

Extend the `impl-gitignore.txt` test at `tests/test_templates.py:2150` with `assert "*/review/" in text`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_impltidy.py tests/test_init.py -k "impl or tidies or leaves_docs_impl or context_cache" tests/test_templates.py -q`
Expected: FAIL — `No such command 'impl'`, missing `moved` note, missing `*/context.md`.

- [ ] **Step 3: Implement**

`cli.py`, after the `plan_app` lines (78-79):

```python
impl_app = typer.Typer(help="Dev work folders: docs/impl/<ticket-id>/.")
app.add_typer(impl_app, name="impl")
```

`cli.py`, new command right after the `plan waves` command:

```python
@impl_app.command("tidy")
def impl_tidy(
    impl_dir: Path = typer.Option(
        Path("docs/impl"), "--impl-dir", help="Where ticket work folders live"
    ),
) -> None:
    """Move flat docs/impl/<id>-{design,plan,context}.md and <id>-review/
    into docs/impl/<id>/. Idempotent, never overwrites, no git — commit the
    renames yourself. Exit 0 after a report."""
    from strata_kb import impltidy

    if not impl_dir.is_dir():
        typer.secho(
            f"--impl-dir '{impl_dir}' does not exist or is not a directory", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    done, conflicts = impltidy.tidy(impl_dir)
    for src, dst in done:
        typer.echo(f"moved: {src} → {dst}")
    for c in conflicts:
        typer.echo(c)
    if not (done or conflicts):
        typer.echo("nothing to tidy")
```

`initcmd.py` `init_repo`, dev branch — after `scaffold_dev_local_overrides(target, report)`:

```python
        done, conflicts = impltidy.tidy(target / "docs" / "impl")
        report.notes.extend(f"moved  {s} → {d}" for s, d in done)
        report.notes.extend(conflicts)
```

and add `from strata_kb import impltidy` to `initcmd.py`'s imports (match the existing `from strata_kb import …` style).

`impl-gitignore.txt` becomes:

```
# The per-ticket context cache is derivable from one full `kb resolve` —
# never committed (C1). Design and plan files ARE committed.
*/context.md

# Review artefacts (diffs, reviewer reports) are derivable from git and the
# review records in the design/plan files — never committed.
*/review/

# Old flat layout, until `kb impl tidy` moves it.
*-context.md
*-review/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_impltidy.py tests/test_init.py tests/test_templates.py -q`
Expected: all pass. If a test in `test_init.py` counts notes exactly for a fresh dev init, it still passes (fresh repo → no moves).

- [ ] **Step 5: Commit** — `feat: kb impl tidy; kb init --kind dev restructures a flat docs/impl`

---

### Task 3: `prlint` reads `<id>/plan.md`

**Files:**
- Modify: `src/strata_kb/prlint.py:1-10` (docstring), `:222-289` (`plan_cmd_test`, `_plan_findings`)
- Modify: `src/strata_kb/cli.py` `--plan-dir` help (pr lint) and `--write-cache` help (resolve)
- Test: `tests/test_prlint.py:265-348`, `tests/test_cli_prlint.py:79-87`

**Interfaces:**
- Consumes: none.
- Produces: `plan_cmd_test(plan_dir, ticket_id)` reads `plan_dir / ticket_id / "plan.md"`.

Depends on: Task 2 (both edit `cli.py`)

- [ ] **Step 1: Update tests to the new layout and add the flat-hint test**

In `tests/test_prlint.py`:
- `_plan` writes `d / ticket / "plan.md"` (`(d / ticket).mkdir(parents=True)` first) instead of `d / f"{ticket}-plan.md"`.
- line 306: `"ATM-7-plan.md"` → `"plan.md"` and add `and "ATM-7" in f.message`.
- lines 336 and 345: write to `d / "ATM-7" / "plan.md"` (mkdir `d / "ATM-7"` with `parents=True`).
- add:

```python
def test_flat_plan_is_plan_missing_with_a_tidy_hint(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ATM-7-plan.md").write_text("cmd.test: `pytest -q`\n", encoding="utf-8")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    (f,) = report.warnings
    assert f.code == "plan-missing"
    assert "kb impl tidy" in f.message
```

In `tests/test_cli_prlint.py:82`: write `plans / "ATM-7" / "plan.md"` (mkdir first).

- [ ] **Step 2: Run to verify failures**

Run: `uv run pytest tests/test_prlint.py tests/test_cli_prlint.py -q`
Expected: FAIL — plan not found at the new path; no tidy hint.

- [ ] **Step 3: Implement**

`plan_cmd_test`: `text = (plan_dir / ticket_id / "plan.md").read_text(encoding="utf-8")`.

`_plan_findings`: `plan_path = plan_dir / ticket_id / "plan.md"`; the not-a-file branch becomes:

```python
    if not plan_path.is_file():
        hint = (
            f" — flat layout {plan_dir / f'{ticket_id}-plan.md'} found: run kb impl tidy"
            if (plan_dir / f"{ticket_id}-plan.md").is_file()
            else " (spike or no plan yet)"
        )
        return [Finding("Testing", "plan-missing",
                        f"{plan_path} not found — the cmd.test check did not run{hint}",
                        level="warning")]
```

Docstrings/help: `docs/impl/<ticket-id>-plan.md` → `docs/impl/<ticket-id>/plan.md` in `prlint.py` docstring, `cli.py` `--plan-dir` help; `docs/impl/<ticket-id>-context.md` → `docs/impl/<ticket-id>/context.md` in the `--write-cache` help; `plan_app` help → `docs/impl/<ticket-id>/plan.md`; `planwaves.py` module docstring line 3 likewise.

- [ ] **Step 4: Run** `uv run pytest tests/test_prlint.py tests/test_cli_prlint.py tests/test_cli_planwaves.py -q` — all pass.

- [ ] **Step 5: Commit** — `feat: kb pr lint reads docs/impl/<id>/plan.md, hints kb impl tidy on a flat plan`

---

### Task 4: usage transcript regex

**Files:**
- Modify: `src/strata_kb/usage/transcript.py:32-43`
- Test: `tests/test_usage_transcript.py:158-183`

**Interfaces:** Produces: `TICKET_PATH_RE` group `impl` = the folder name in `docs/impl/<id>/(design|plan).md`.

Depends on: none

- [ ] **Step 1: Update tests**

- line 159-162: comment and row → `docs\\impl\\ATM-7\\plan.md` (Python literal `"see docs\\impl\\ATM-7\\plan.md"`).
- line 176: `"now docs/impl/M-stock-US2/design.md"`.
- add:

```python
def test_the_flat_impl_layout_no_longer_sets_the_cursor(tmp_path: Path):
    path = write_transcript(
        tmp_path, [user_row("see docs/impl/ATM-7-plan.md"), usage_row("a1")]
    )
    (row,) = transcript.rows_from_transcript(path, actor="dev")
    assert row.ticket is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_usage_transcript.py -q` — FAIL on the three.

- [ ] **Step 3: Implement** — comment example `docs\\impl\\x\\plan.md`; second alternative of `TICKET_PATH_RE`:

```python
    rf"|docs{_SEP}impl{_SEP}(?P<impl>[^/\\\"\s]+?){_SEP}(?:design|plan)\.md"
```

- [ ] **Step 4: Run** `uv run pytest tests/test_usage_transcript.py -q` — all pass.

- [ ] **Step 5: Commit** — `feat: usage ledger follows docs/impl/<id>/ paths`

---

### Task 5: wrappers, QUICKSTARTs, Intake tidy step

**Files:**
- Modify: every `src/strata_kb/templates/init/{claude-skill,claude-command,cursor,copilot}-dev-*` file listed by the rewrite script, `QUICKSTART-dev.md`, `QUICKSTART-ba.md`
- Test: `tests/test_templates.py`, `tests/test_cli_context.py:186`

**Interfaces:** none (text only).

Depends on: Task 2 (test_templates.py also edited there)

- [ ] **Step 1: Mechanical rewrite** — run once from the repo root (scratch script, not committed):

```python
import re
from pathlib import Path

SUBS = [
    (re.compile(r"docs/impl/<(ticket-id|id)>-review"), r"docs/impl/<\1>/review"),
    (re.compile(r"docs/impl/<(ticket-id|id)>-(design|plan|context)\.md"), r"docs/impl/<\1>/\2.md"),
    (re.compile(r"docs/impl/<(ticket-id|id)>-\{design,plan\}\.md"), r"docs/impl/<\1>/{design,plan}.md"),
]
files = [*Path("src/strata_kb/templates/init").glob("*.md"), Path("tests/test_templates.py")]
for f in files:
    text = f.read_text(encoding="utf-8")
    new = text
    for rx, rep in SUBS:
        new = rx.sub(rep, new)
    if new != text:
        f.write_bytes(new.encode("utf-8"))
        print(f)
```

`-`→`/` keeps line lengths, so no re-wrapping. Write bytes so line endings are untouched.

- [ ] **Step 2: Hand edits**
- `claude-command-dev-implement-ticket.md:65`: `` `docs/impl/<ticket-id>/design.md` and `-plan.md` `` → `` `docs/impl/<ticket-id>/design.md` and `plan.md` ``.
- `QUICKSTART-dev.md` "Where work lives": bullets read `docs/impl/<ticket-id>/design.md`, `/plan.md`, `/context.md`, plus a bullet `docs/impl/<ticket-id>/review/` — per-task diffs, reviewer reports, branch diff, merge-risk report; gitignored. Replace "`kb init` never touches your `docs/impl/` content: it only ever adds …" with: "`kb init` never edits your `docs/impl/` content: it adds `docs/impl/.gitkeep` and `docs/impl/.gitignore`, and moves an old flat layout (`<id>-design.md`, `<id>-plan.md`, `<id>-context.md`, `<id>-review/`) into `<id>/` — never overwriting; commit the renames." Same correction in "Upgrading" (line ~353: "Anything you authored under `docs/impl/` is not scaffolding: `kb init` never reads, writes, or overwrites it" → "… `kb init` only moves flat `<id>-*` entries into `<id>/` (also `kb impl tidy`), never edits or overwrites them").
- All four `dev-implement-ticket` wrappers (`claude-skill-`, `claude-command-`, `cursor-`, `copilot-…prompt.md`), Intake bullet: prepend "run `kb impl tidy` first — it moves a flat `docs/impl/<id>-*` layout into `docs/impl/<id>/` (no CLI → move them by hand);".

- [ ] **Step 3: Tests**
- `tests/test_templates.py`: the script already rewrote path literals and golden blocks. Fix the leftovers by hand: line ~1219 `"<ticket-id>-context.md"` → `"<ticket-id>/context.md"`; line ~1348 needle `"-context.md"` → `"/context.md"`. Add:

```python
def test_dev_implement_ticket_runs_impl_tidy_at_intake():
    for name in ("claude-skill-dev-implement-ticket.md",
                 "claude-command-dev-implement-ticket.md",
                 "cursor-dev-implement-ticket.md",
                 "copilot-dev-implement-ticket.prompt.md"):
        assert "kb impl tidy" in _read_init_template(name), name


def test_no_wrapper_names_the_flat_impl_layout():
    import re
    flat = re.compile(r"docs/impl/<(ticket-id|id)>-")
    for f in resources.files("strata_kb").joinpath("templates/init").iterdir():
        if f.name.endswith(".md"):
            assert not flat.search(f.read_text(encoding="utf-8")), f.name
```

(use the module's existing `resources` import / `_read_init_template` helper; adapt the iteration to whatever the file already uses to list templates).
- `tests/test_cli_context.py:186`: `tmp_path / "docs" / "impl" / "T-7" / "context.md"`.

- [ ] **Step 4: Run** `uv run pytest tests/test_templates.py tests/test_cli_context.py tests/test_init.py -q` — all pass.

- [ ] **Step 5: Commit** — `docs: dev wrappers and QUICKSTARTs use docs/impl/<id>/; Intake runs kb impl tidy`

---

### Task 6: README, guides, CHANGELOG, full suite

**Files:**
- Modify: `README.md:751-752`, `docs/src/guide-dev.en.md:225-228,244,559`, `docs/src/guide-dev.vi.md:227-230,247,564`, `CHANGELOG.md`
- Regenerate (best effort): `docs/strata-guide-dev.{en,vi}.pdf`

Depends on: Tasks 1-5

- [ ] **Step 1:** run the Task 5 rewrite script over `README.md` and `docs/src/guide-dev.*.md`; in each guide's `docs/impl` table add one sentence below it (en: "`kb init --kind dev` and `kb impl tidy` move an old flat layout into these folders."; vi: "`kb init --kind dev` và `kb impl tidy` tự dời layout phẳng cũ vào các folder này."). Add `kb impl tidy [--impl-dir]` row to each guide's CLI table next to `kb plan waves` (exit `0` after a report, `1` when the dir is missing).
- [ ] **Step 2:** `CHANGELOG.md` under `## Unreleased` (create the heading if absent, above the latest release):

```
- Dev repos: each ticket's work lives in one folder — `docs/impl/<ticket-id>/{design.md, plan.md, context.md, review/}` instead of flat `docs/impl/<ticket-id>-*`. New `kb impl tidy` moves a flat layout (idempotent, never overwrites, no git); `kb init --kind dev` runs it, and `dev-implement-ticket` runs it at Intake. `kb pr lint` reads `docs/impl/<id>/plan.md` and, on a flat plan, says to run `kb impl tidy`; the usage ledger follows the new paths.
- Migration for an existing dev repo: re-run `kb init --kind dev`, then commit the renames.
```

- [ ] **Step 3:** `python docs/src/build_pdf.py guide-dev.en guide-dev.vi`. It needs macOS fonts; if it fails on this machine, leave the PDFs and say so in the PR Notes.
- [ ] **Step 4:** full suite `uv run pytest -q` and `uv run ruff check .` — record output. Known pre-existing failures on main (2) are not regressions; name them.
- [ ] **Step 5: Commit** — `docs: README, dev guides and CHANGELOG for per-ticket docs/impl folders`
