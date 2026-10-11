# Review follow-ups (3e-1) Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-11-review-followups-design.md`

**Constraints:**
- Release **1.16.0**.
- Every fix lands with a test that fails on `main`.
- Test command: `uv run pytest -q -p tikstub`.

## Deviations from the spec

Recorded during implementation:

- **Summary rows.** `--summary` shows at most 6 phase rows, plus an
  "N more phase(s)" row, rather than "8 lines".
- **The `claude-command-dev-handover` copy.** It is a full copy that was
  not merged in 3d, so it got the same Usage wording by hand. The
  template tests pin both.
- **Reversed tests.** The tests that pinned "no `## Usage` in the PR"
  (1.7.0) now pin the new contract instead. This follows the decision
  taken on 2026-10-11.
- **C7.** The negative test was checked by sabotage: when the document
  is also published, all four test functions fail.

---

- [x] **Task 1.** G15: natural sort in `svcnote` and its tests.
- [x] **Task 2.** C7: `tests/test_unpublished_never_leaks.py`.
- [x] **Task 3.** `kb usage report --with` and `--summary`, with
  `tests/test_usage_with.py`.
- [x] **Task 4.** The Usage block in the `dev-handover` templates and in
  the PR template, plus a `kb pr lint` test.
- [x] **Task 5.** `ticketstale` and `kb ticket stale`, `kb-doctor.yml`
  for ba and dev, and the README.
- [x] **Task 6.** CHANGELOG, version, full suite, T0, PR.
