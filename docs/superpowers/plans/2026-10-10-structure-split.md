# Structure split Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-structure-split-design.md`

**Constraints:**
- Release **1.15.1**.
- Test command: `uv run pytest -q -p tikstub`.
- T0 stays clean.
- Tests change only import paths, plus the new structural tests.

## Deviations from the spec

Recorded during implementation.

---

- [x] **Task 1.** `codeingest/types.py` and `localgit.py`; the tail
  imports go; import-order tests.
- [ ] **Task 2.** `serving/` (`config`, `auth`, `ratelimit`); rewire
  `web`, `mcp`, `intake` and the tests; layering test.
- [ ] **Task 3.** `doctor/` package with `issues.py` and `checks/*`.
- [ ] **Task 4.** CHANGELOG, version, full suite, T0, PR.
