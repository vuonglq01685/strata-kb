# Restore `kb approve` + `/kb-approve` slash command — Design

**Date:** 2026-07-15
**Status:** Approved
**History:** `kb approve` shipped in PR #3 (spec `2026-07-11-review-automation-design.md`)
and was removed in `8c7dfd5`/`6116566` when the hub federation became the single
source of truth (review gate = hub PR merge). The user still wants a manual
SME step that flips section `status: summarized → reviewed` in
`_manifest.yaml` on authoring repos.

## Decisions

### 1. `kb approve` CLI — restored verbatim from history

Restore `src/center_kb/review.py` and the `approve` Typer command from
`6116566^` unchanged (all consumed APIs — `models.load_yaml_model/save_yaml_model`,
`gitio.git_root/read_at`, `diff.diff_doc`, the `git_kb` test fixture — still
exist with the same signatures):

```
kb approve [DOC_ID] [--section <id> ...] [--all-changed] [--against <rev>] [--kb-dir <path>]
```

- `kb approve <doc>` — flip every `summarized` section of the doc.
- `--section` (repeatable) — flip only those; unknown id → `[error]` + exit 1.
- `--all-changed --against <rev>` — flip sections added/changed vs `<rev>`
  (doc scoped when DOC_ID given, else every doc in `index.yaml`).
- `pending` sections are skipped with a stderr warning; `reviewed` untouched
  (idempotent). Manual mode with nothing to flip → exit 1; `--all-changed`
  with nothing to do → exit 0 ("nothing to approve").
- Tests `tests/test_review.py` + `tests/test_cli_approve.py` restored from
  the same rev.

### 2. NOT restored

The CI auto-flip (`kb-review.yml` workflow + its init template) stays
dropped — the hub PR merge remains the federation review gate. `reviewed`
now means "an SME ran `kb approve` on the authoring repo", a deliberate
manual act, not an automated consequence of a merge.

### 3. `/kb-approve` slash command — new (did not exist before)

Four thin wrapper templates in `COMMON_TEMPLATES` (both kinds author KBs):
`.claude/skills/kb-approve/SKILL.md`, `.claude/commands/kb-approve.md`,
`.github/prompts/kb-approve.prompt.md`, `.cursor/commands/kb-approve.md`.
Workflow: run `kb status` to show the docs and their pending/summarized
sections, confirm with the user what to approve, run `kb approve ...`, relay
output. Hard rules: never edit `_manifest.yaml` by hand; only flip via the
CLI; relay errors verbatim.

### 4. Docs

- QUICKSTART-child: the Summarize step gains the follow-up sentence — after
  `kb build` passes and you have checked the summaries, run
  `kb approve <doc-id>` (or `/kb-approve`) to mark them `reviewed` before
  publishing. CLI reference gains `kb approve`.
- QUICKSTART-hub: CLI reference gains `kb approve`.
- README command table/flow mentions gain `kb approve`.

## Testing

- Restored suites must pass as-is (fixture unchanged).
- `test_init.py`: assistant-parity test gains `kb-approve` for both kinds;
  wrapper content assertions (invokes `kb approve`; forbids hand-editing
  `_manifest.yaml`).

## Acceptance criteria

- `kb approve demo-doc` flips summarized → reviewed; idempotent re-run.
- `--all-changed --against <rev>` flips exactly the changed/added sections.
- Both kinds scaffold all four `/kb-approve` wrappers.
- No CI workflow re-added.
