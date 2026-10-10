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

Recorded during implementation:

- **stdout, not stderr.** The guard prints on stdout, like the arms it
  replaces, so no command's output moves streams. The spec is updated to
  match.
- **`hub_ref` stays unresolved.** `PublishPlan.hub_ref` is `None` for a
  child or dev publish. `require_hub()` still runs after the `-code`
  refresh and the unreviewed gate, as before. Resolving it inside `plan()`
  would have changed which error a repo with no `hub:` sees first.
- **Patchable config.** `doctor.run()` calls `config_mod.load_config`
  through the module, so tests that patch `strata_kb.config.load_config`
  still reach it. Before the move they reached it through the CLI's lazy
  import.
- **Arms the guard made redundant.**
  - 9 arms are deleted. They only printed `str(exc)` for a `KbError`.
  - 7 tuples drop their `KbError` members.
  - The three publish arms shrink to their non-`KbError` classes.
  - Arms that add guidance stay: the unreviewed gate, the
    `ci-publish` step summary, and `mcp-setup`'s `.env` message.

---

- [x] **Task 1.** `.git-blame-ignore-revs`, the spec and the plan.
- [x] **Task 2.** Five errors join `KbError`; the allowlist shrinks.
- [x] **Task 3.** `_GuardedGroup` plus guard tests; drop the redundant
  arms.
- [x] **Task 4.** `publish.plan()` plus `tests/test_publish_plan.py`;
  `cli.publish` slims down.
- [x] **Task 5.** `doctor.run()` plus `tests/test_doctor_run.py`;
  `cli.doctor` slims down.
- [x] **Task 6.** CHANGELOG, version, full suite, T0, PR.
