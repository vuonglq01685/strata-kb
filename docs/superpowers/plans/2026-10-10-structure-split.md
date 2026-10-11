# Structure split Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-structure-split-design.md`

**Constraints:**
- Release **1.15.1**.
- Test command: `uv run pytest -q -p tikstub`.
- T0 stays clean.
- Tests change only import paths, plus the new structural tests.

## Deviations from the spec

Recorded during implementation:

- **Logger name.** The auth logger keeps its name, `strata_kb.web.auth`,
  after the move to `serving/`. Operators and one test filter on it.
- **One test changed beyond import paths.** `test_doctor.py` patches
  `doctor.checks.assets.ASSET_SIZE_WARN_BYTES` instead of the re-export,
  because the patch has to land where the check reads the name.
- **The stdin guard.** The codeingest stdin guard now covers
  `localgit.py`, where the subprocess call moved. It also asserts that
  `core` has none.

---

- [x] **Task 1.** `codeingest/types.py` and `localgit.py`; the tail
  imports go; import-order tests.
- [x] **Task 2.** `serving/` (`config`, `auth`, `ratelimit`); rewire
  `web`, `mcp`, `intake` and the tests; layering test.
- [x] **Task 3.** `doctor/` package with `issues.py` and `checks/*`.
- [x] **Task 4.** CHANGELOG, version, full suite, T0, PR.
