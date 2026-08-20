# Phase 5 Stage A — handover notes for Stages B, C and D

Stage A is complete: `feat/phase-5-dev-agent`, commits `26097a6..e76333c`, version 0.16.0.
Full suite green (1263 passed / 5 skipped / 1 pre-existing warning at the release commit).

This file exists because five things learned while executing Stage A are obligations on the
*later* stages, and neither sibling plan currently discharges them. They are not defects in
what shipped — they are debts the next plan pays.

## 1. Task C3 will not retire Stage A's orchestrator caveat

Task A6 added a staging caveat to the four `dev-implement-ticket` wrappers: the Ground step
sends the agent at `<repo_id>-code` and `<repo_id>-svc`, so the wrappers say the search is
skipped **until Stages B and C ship**.

Stage C's Task C3 ("retire the Stage-A interim fallbacks") will miss it twice over:

- Its **Files** list and its `test_dev_wrappers_no_longer_carry_the_stage_a_interim_fallbacks`
  iterate only `dev-plan`, `dev-execute` and `dev-handover`. The orchestrator is not in either.
- Its needle is `assert "until Stage B" not in text`. The orchestrator's phrasing is
  `until Stages B and C ship` — **"until Stages B" does not contain "until Stage B"**, so even
  a widened file list would pass with the caveat still in place.

Whoever runs Stage C must widen both the file list and the needle. Otherwise kind `dev` keeps
telling Devs to skip a search that works by then.

## 2. `cannot publish yet` is pinned by a test, and publishing goes live in Stage B

`QUICKSTART-dev.md` says the repo **cannot publish yet**, and `tests/test_init.py`'s
`test_quickstart_dev_content` asserts that exact phrase. Publishing becomes real at the end of
**Stage B** (Task B9 scaffolds `kb-code.yml`, which republishes `-code` on every merge), but the
plans only revisit `QUICKSTART-dev.md` in **Task D2** — the last task of the whole phase.

Between B9 and D2 the shipped onboarding page understates the product, and the test freezes the
understatement in until someone edits both. Stage B should either retire the caveat with B9 or
accept the window knowingly.

The same applies to the caveats in `config-dev.yaml` (comments naming Stage B and Stage C),
`cli.py`'s `KIND_DESCRIPTIONS` and post-init next-steps, `README.md`'s kind table, and the
`dev-handover` wrappers' amend-findings step. **Grep `until Stage`, `cannot publish yet` and
`not yet` across `src/center_kb/templates/init/`, `src/center_kb/cli.py` and `README.md` before
closing each stage.**

## 3. Three counts are deliberate trip-wires — bump them consciously

- `tests/test_templates.py` — `assert len(names) == 20` in the shared-block canon test. A sixth
  workflow skill makes it 24.
- `tests/test_init.py` — `assert len(expected_files("dev")) == 26`. Stage B's `kb-code.yml` row
  and Stage C's `dev-code-seed` plus reused authoring wrappers each raise it.
- `tests/test_templates.py` — `SHARED_BLOCK_TEXT` holds the three shared blocks' canonical text
  verbatim. Changing a shared block is now a deliberate two-place edit: the 20 wrappers and the
  canon. That is the point; do not "fix" the test by regenerating canon from a wrapper.

`LANDED_DEV_WORKFLOW_SKILLS` is an alias of `DEV_WORKFLOW_SKILLS` because all five skills
landed in Stage A. Several tests read wrapper files while iterating that tuple, so **a stage
that adds a sixth skill must land its four wrappers in the same task that names it.**

## 4. What the wrapper tests do and do not guard

Assertions about a wrapper's own prose are matched against `_dev_wrapper_body(name)`, which
strips the three shared blocks — without that, any needle the shared blocks satisfy is
unfalsifiable, which is how a batch of assertions was silently vacuous mid-plan. Assertions
about shared-block content are matched against the whole text, and the blocks themselves are
now anchored to canonical text rather than to each other.

Still unguarded by design: each wrapper's own prose outside the shared blocks
(~1800-2800 characters per file), covered only by the named body needles. Three prose variants
per skill are authored independently; only `copilot-*` ≡ `cursor-*` is locked by a test.

## 5. Minor findings carried, not fixed

Triaged as safe to carry by the whole-branch review. Recorded so they are not rediscovered as
new:

- The four `claude-command-dev-*.md` invokers compress their skill's procedure into one dense
  paragraph; several read as a run of short sentences, and two clauses in
  `claude-command-dev-design.md` are near-verbatim rephrasings of the skill's wording.
- `claude-command-dev-plan.md` never spells out that option 1 is `/dev-execute <id>`.
- `"ticket id"` in the `dev-handover` PR-contents test is co-satisfied three ways in the command
  wrapper; the other five needles in that test carry it.
- `claude-skill-dev-handover.md`'s first Steps bullet says the freshness block "runs again right
  here" while that block is the same file's first section.
- The `dev-handover` wrappers wrap authored prose slightly narrower than the other four skills.
- `tests/test_templates.py`'s copilot ≡ cursor test skips the frontmatter line rather than
  asserting what it holds, and nothing asserts `SHARED_BLOCK_TEXT`'s key set matches
  `SHARED_BLOCKS`' — a future fourth shared block could be added unanchored.
- `src/center_kb/initcmd.py`'s `DEV_TEMPLATES` comment still describes publishing in the present
  tense. Internal comment, not shipped scaffold.
- Six commits on this branch lack the `Co-Authored-By` trailer the surrounding commits carry.
  Left for a human to decide; reviewed history was not rewritten over it.
