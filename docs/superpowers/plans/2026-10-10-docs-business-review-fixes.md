# Docs and business review fixes Implementation Plan

**Goal:**
- Copyrighted sources cannot be committed by following the docs.
- No credential sits in a committed config.
- Every README claim the 2026-10-10 review flagged matches the code, and a
  test pins it.

**Spec:** `docs/superpowers/specs/2026-10-10-docs-business-review-fixes-design.md`

## Global constraints

- Release **1.11.0**: `pyproject.toml`, the `strata-kb` entry in `uv.lock`,
  and the CHANGELOG heading.
- Test command: `uv run pytest -q -p tikstub`. `tikstub` is the scratchpad
  stand-in for `cl100k_base`, as in 1b.
- Lint: `uv run ruff check .`
- README pins use the whitespace-normalised phrase style of
  `tests/test_readme.py`.

## Deviations from the spec (decided while implementing)

- **No "upgrade the old exact text" logic (spec §1).** `kb init` already
  refreshes every non-protected scaffold file on each run, and
  `source/.gitignore` is one of them. Pointing a second map entry at the
  new template is enough: an old `*.pdf` file is replaced on the next
  `kb init`. A hand-edited one is replaced too, as every scaffold file
  always was. The new rule is strictly broader, so nothing it ignored
  before becomes tracked.
- **`kb usage` subcommands** are documented in a table under §6, beside the
  existing `kb usage` paragraph, not in a separate subsection.

---

### Task 1: Ignore-everything source folders (spec §1)

**Files:**
- `templates/init/source-gitignore.txt`
- `initcmd.py`: a second map entry (see the deviation above).
- Tests: `tests/test_init.py` (new cases).

- [ ] Write failing tests. Fresh scaffold → both files present, and
  `git check-ignore` matches. Old text → upgraded. Edited file → left
  alone, with a note.
- [ ] Implement.

### Task 2: Doctor warnings (spec §1, §2)

**Files:**
- `doctor.py`: `check_source_dirs` and `check_config_credentials`, wired
  into `kb doctor` for every kind.
- Tests: `tests/test_doctor_source_and_config.py` (new).

- [ ] Write failing tests (tracked PDF, `.gitignore`-only folder, tracked
  credentialed config, untracked config, no credential), then implement.

### Task 3: Config templates + README + QUICKSTART-child wording (spec §2–§6)

**Files:**
- `templates/init/config-*.yaml`
- `templates/init/QUICKSTART-child.md`
- `README.md`
- Tests: `tests/test_readme.py` (new pins).

- [ ] Write the failing README pins first:
  - `kb stats` ratio and saving
  - no ">90%"
  - nine-step, matching the skill's step count
  - one round by default, hub first, agent-reported
  - no "Enforced throughout", "Prompt-only" present
  - every typer command in §6
- [ ] Edit the docs until the pins pass. Check existing template tests
  for pinned wording.

### Task 4: Release

- [ ] CHANGELOG 1.11.0 (including the `rel.*`/AST record) and the version
  bump.
- [ ] Full suite, then ruff, then commit, push and open the PR.
