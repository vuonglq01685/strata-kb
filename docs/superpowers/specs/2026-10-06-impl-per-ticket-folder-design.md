# docs/impl per-ticket folder — design

Date: 2026-10-06
Status: approved (brainstorming)

## Problem

A dev repo keeps every ticket's work flat under `docs/impl/`:
`<id>-design.md`, `<id>-plan.md`, `<id>-context.md`, `<id>-review/`. With
a few tickets in flight the folder becomes a long interleaved list that is
hard to manage. Everything for one ticket should live in one folder, and an
existing repo must be restructured automatically when it upgrades.

## Layout

```
docs/impl/
  .gitkeep  .gitignore
  <ticket-id>/
    design.md   plan.md        (committed)
    context.md  review/        (gitignored)
```

Short names inside the folder; the folder carries the ticket id.

## Core: `impltidy.py`

New module `src/strata_kb/impltidy.py`, shaped like `tickettidy.py`.

- `plan_moves(impl_dir)` scans only entries directly under `impl_dir`:
  - file `^(?P<id>.+)-(design|plan|context)\.md$` → `<id>/<kind>.md`
  - directory `^(?P<id>.+)-review$` → `<id>/review/`
  - anything else (`.gitkeep`, `.gitignore`, existing ticket folders,
    unrelated files) is left alone.
- Moves are applied by the existing `tickettidy.apply_moves`: an existing
  destination is a conflict (source left in place, never overwritten); an
  `OSError` is a conflict, not a crash. Idempotent — a second run moves
  nothing.
- No git: a plain rename, as `kb ticket tidy` does. Git detects the rename
  when the Dev stages it. Never commits.

## Callers

1. **`kb impl tidy [--impl-dir docs/impl]`** — new command. Prints
   `moved: src → dst`, `conflict: …`, or `nothing to tidy`; exit 0 after
   the report. A missing `--impl-dir` is exit 1, as `ticket tidy` does.
2. **`kb init --kind dev`** — runs the tidy after writing scaffold and
   prints the same lines. Other kinds never touch `docs/impl/`.
3. **`dev-implement-ticket`** (claude skill + command, cursor, copilot) —
   runs `kb impl tidy` at Intake. Covers a teammate who pulled the
   committed renames but still has gitignored `context.md`/`review/` flat
   on disk.

`impl-gitignore.txt` becomes `*/context.md` and `*/review/`, keeping
`*-context.md` and `*-review/` so a teammate's not-yet-tidied flat files
never show in `git status`.

## Readers — new layout only

No code reads both layouts.

- `prlint.py`: `plan_cmd_test` and `_plan_findings` read
  `plan_dir / id / "plan.md"`. When that is absent but `plan_dir /
  f"{id}-plan.md"` exists, the `plan-missing` warning adds
  `flat layout — run kb impl tidy`. Still a warning: an open PR is not
  blocked.
- `usage/transcript.py`: the `impl` branch of `TICKET_PATH_RE` matches
  `docs/impl/<id>/(design|plan).md`; the stem is the folder name.
- `cli.py`: help text for `plan_app`, `--write-cache`, `--plan-dir`. `kb
  plan waves` and `kb resolve --write-cache` take the path from the caller
  — no logic change.

## Text

Mechanical path change, `docs/impl/<ticket-id>-X.md` →
`docs/impl/<ticket-id>/X.md` and `<ticket-id>-review/` →
`<ticket-id>/review/`:

- the 20 dev wrappers (claude skill, claude command, cursor, copilot ×
  design, plan, execute, handover, implement-ticket), including the
  re-entry rules in `dev-implement-ticket`; implement-ticket also gains the
  `kb impl tidy` Intake step;
- `QUICKSTART-dev.md` "Where work lives" and "Upgrading": drop "kb init
  never touches docs/impl/"; say it only moves flat `<id>-*` entries into
  `<id>/`, never edits or overwrites them;
- `QUICKSTART-ba.md`, `docs/src/guide-dev.{en,vi}.md` (PDFs rebuilt by the
  usual flow);
- docstrings in `planwaves.py` and `prlint.py`.

## Testing (TDD)

- `tests/test_impltidy.py`: all four kinds move; a `-review` folder moves
  with its contents; second run is `nothing to tidy`; existing destination
  is a conflict and keeps the source; `.gitkeep`, `.gitignore`, ticket
  folders and unrelated files untouched.
- `kb init --kind dev` on a flat repo moves and prints `moved:`; `kb init
  --kind ba` leaves `docs/impl/` as is.
- CLI `kb impl tidy`: output and exit 0.
- `prlint`: reads `<id>/plan.md`; flat layout gives the warning with the
  tidy hint.
- `transcript`: matches `docs/impl/ABC-12/plan.md` (also the `\\` Windows
  form); no longer matches `ABC-12-plan.md`.
- Existing tests that use the old paths (e.g. `test_cli_context.py`)
  updated.

## Release

`CHANGELOG.md` under Unreleased, one entry plus migration line: re-run
`kb init --kind dev`, commit the renames. No version bump.

## Out of scope

Dual-layout reads, auto-commit, a `kb doctor` flat-layout warning — `kb
init` and the Intake tidy already restructure.
