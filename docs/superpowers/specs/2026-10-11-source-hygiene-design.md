# Source hygiene: module docstrings, no internal-review provenance in src/

**Status:** approved design (wave 3 scope agreed 2026-10-11)
**Source:** §8 đợt 3 item 10 (the part 3a left open) and §4.1 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3e-2, the last batch of wave 3.

## Goal

| Finding | Today |
|---|---|
| §4.1 docstrings | 40 modules under `src/strata_kb` have no module docstring, including `cli.py`, `publish.py`, `intake.py` and `searchdb.py`. Three of them are empty package `__init__.py` files. |
| §4.1 provenance | About 450 comment and docstring lines in `src/` cite internal review artefacts, for example "F-D9 finding 2", "Wave G fix round 2, item 7", "wave I-1 round 4", "spec 2026-09-25 §4.1", "ruling P53" and "HIGH-1 (round 4)". The rationale is good, but it points into documents a reader does not have. |

## Design

### 1. Module docstrings

- Every module under `src/strata_kb` opens with a docstring.
- The house style is the one `usage/ledger.py` already uses:
  - a `name — purpose` line;
  - then one short paragraph covering what the module owns, its entry points, and the invariant a reader must know.
- An empty `__init__.py` gets one line.

### 2. Provenance out, rationale kept

Each tagged comment is rewritten so it stands on its own:

- **The tag goes.** This covers finding ids, waves, rounds, severity labels from a review, brief rulings, reviewer names, and review or spec dates and sections.
- **The rationale stays:** what the code does, why, the failure it prevents, and the alternative that was rejected.
- **History becomes a warning or goes.** "used to X (round 3)" turns into a present-tense warning when it still guards something, and is dropped when it is only history.
- **No ADR files or CHANGELOG entries are added for the moved text.**
  - The CHANGELOG already records each release's changes.
  - Git history keeps the old comments together with their tags.
  - The rationale that matters stays next to the code it explains, which is where a reader needs it.

### 3. Guard

New test file: `tests/test_source_hygiene.py`.

- **`test_module_has_a_docstring`** is parametrized over every module.
- **`test_no_comment_points_at_an_internal_review`** checks every line of `src/` against `_PROVENANCE_RE`.
  - The regex covers the known shapes: `F-D9`, `Wave G`, `fix round`, `round 4`, `P45`, `spec 2026-…`, `… review`, `HIGH-1`, `Important 3` and `roadmap B4`.
  - Two parametrized tests pin it. One checks that it catches those shapes. The other checks that it leaves ordinary prose alone: `L2`, "wave n" in the plan-waves docstring, "round-trip", "at most 3 rounds".

## Out of scope

- **Comments in `tests/`.** About 430 lines carry the same tags. Test comments are read next to the assertion they explain, and a test name already carries the intent. A later pass can extend the guard to `tests/`.
- **Rewording rationale that carries no tag.**

## Testing

- `tests/test_source_hygiene.py` as described in the Guard section.
- The full suite. The change touches only comments and docstrings, so no behaviour changes.
- T0 (ruff check, ruff format, pyright).

## Delivery

One PR, release **1.16.1**. There is no behaviour change; only comments and docstrings change, plus the guard test.
