# Template bodies Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-11-template-bodies-design.md`

**Constraints:**
- Release **1.15.2**.
- Every rendered template matches the pre-change sha256 snapshot.
- Test command: `uv run pytest -q -p tikstub`.

## Deviations from the spec

Recorded during implementation:

- **The "3,054 lines".** The review counted all of `test_templates.py`
  as sync tests. Only one 4-line test, the full sa-ticket-ground
  claude-vs-cursor equality, became a tautology, and it is kept. The rest
  checks content.
- **Stub shape.** Stubs may keep a short intro. `ba-mission-plan`'s
  Copilot and Cursor intro differs from Claude's, so stubs are limited to
  20 lines of their own rather than a single heading.

---

- [x] **Task 1.** Snapshot sha256 of all 168 templates. Convert 13 skills
  (29 files) to stubs plus `bodies/`.
- [x] **Task 2.** `initcmd.read_template()`; `kb init` and the test
  helpers read through it; verify every rendered template against the
  snapshot.
- [x] **Task 3.** `tests/test_template_bodies.py`.
- [x] **Task 4.** CHANGELOG, version, full suite, T0, PR.
