# CLI guard and library publish/doctor Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-cli-guard-library-design.md`

**Constraints:**
- Release **1.15.0**: bump `pyproject.toml` and the `strata-kb` entry in
  `uv.lock`, and add a CHANGELOG heading.
- Test command: `uv run pytest -q -p tikstub`. `tikstub` is a scratchpad
  plugin that stands in for `cl100k_base`.
- T0 stays clean: `ruff check .`, `ruff format --check .`, `pyright`.
- The CLI's text and exit codes stay unchanged. The existing CLI tests are
  the oracle.

## Deviations from the spec

Recorded during implementation.

---

- [ ] **Task 1.** `.git-blame-ignore-revs`, the spec and the plan.
- [ ] **Task 2.** Five errors join `KbError`; the allowlist shrinks.
- [ ] **Task 3.** `_GuardedGroup` plus guard tests; drop the redundant
  arms.
- [ ] **Task 4.** `publish.plan()` plus `tests/test_publish_plan.py`;
  `cli.publish` slims down.
- [ ] **Task 5.** `doctor.run()` plus `tests/test_doctor_run.py`;
  `cli.doctor` slims down.
- [ ] **Task 6.** CHANGELOG, version, full suite, T0, PR.
