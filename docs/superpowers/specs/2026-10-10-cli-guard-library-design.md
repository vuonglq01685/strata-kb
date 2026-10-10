# One error family, one CLI guard, publish and doctor as library calls

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §4.2 and §8 đợt 3 item 8 (part 1) of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3b of wave 3. 3a (#86) added the tooling gate.
**Approach,** as chosen on 2026-10-10:
- The CLI-reachable errors join `KbError`. The server-only errors stay
  allowlisted.
- One guard at the root click group.
- `publish.plan()` and `doctor.run()` move into the library in the same
  PR.

## Goal

| Problem | Today |
|---|---|
| Five errors a CLI command can meet sit outside `KbError`: `GitError`, `IndexBusyError` (both `RuntimeError`), and `CodeIngestError`, `SvcNoteError`, `RunnerError` (all bare `Exception`). | Each call site re-lists them in an `except (...)` tuple. The one it forgets reaches the user as a traceback. |
| `cli.py` hand-writes 113 `typer.secho(..., RED)` calls and 118 `raise typer.Exit(1)`. Many of them only print `str(exc)`. | Boilerplate that has to be repeated, and can be forgotten, at every new call site. |
| `publish()` in `cli.py` (~220 lines) decides the route: hub-to-hub, self-publish, intake or plain. `doctor()` (~175 lines) assembles checks by kind and computes the exit code. | That business logic can only be tested through `CliRunner`. |

## Design

### 1. The `KbError` family

- These change base to `KbError`:
  - `gitio.GitError`
  - `searchdb.IndexBusyError`
  - `codeingest.core.CodeIngestError`
  - `svcnote.SvcNoteError`
  - `llm.RunnerError`
- `KbError` derives from `RuntimeError`. For the first two that is
  additive. The last three move from `Exception` to `RuntimeError`.
  `src/` has no `except RuntimeError`, so no handler starts catching
  something new by accident. The test suite is the proof.
- These stay in the allowlist with their rulings, because they map to
  HTTP responses and never reach the CLI:
  - `IntakeError`
  - `GHAppError`
  - `RegistryError`
  - `SnapshotCorruptError`
  - `_LoginBodyTooLarge`
- The `ValueError` and `LookupError` families (`KBContextError`,
  `InvalidLevelError`, `TooManyTagsError`, `AmbiguousDocError`) also stay
  allowlisted. Changing their base would break callers that catch
  `ValueError`.
- The allowlist entries for the five that join are removed. The sweep
  test then enforces membership.

### 2. `_cli_guard`: one place

- `app = typer.Typer(cls=_GuardedGroup)`. `_GuardedGroup(TyperGroup)`
  overrides `invoke()`: a `KbError` that escapes any command, sub-app
  included, prints `str(exc)` in red to stderr and exits 1.
- This sits at the root group, so `CliRunner`, the `kb` script and
  `python -m strata_kb` all get it.
- Exit codes are unchanged (README §16): 1 for an error. A `typer.Exit`
  raised by a command passes through untouched.
- **Clean-up.** An `except` arm whose whole body is
  `secho(str(exc), RED)` plus `raise typer.Exit(1) from None` is deleted
  wherever the class it catches is now a `KbError`.
  - An arm that adds guidance, such as "fix the file, or remove it…", is
    kept. That guidance is the reason the arm exists.
  - An arm that catches non-`KbError` classes (`OSError`, the YAML and
    pydantic errors) keeps catching those.

### 3. `publish.plan()` → route, then run

- `publish.plan(kb_dir, hub_flag, repo_id_flag, mode) -> PublishPlan`.
- `PublishPlan` is a frozen dataclass:
  - `route`: `"federation"` (hub-to-hub), `"intake"` or `"snapshot"`
    (plain publish or hub self-publish);
  - `hub_ref`;
  - `repo_id`;
  - `self_publish`;
  - `refresh_code` (`cfg.kind == "dev"`).
- `plan()` raises `PublishError`, a `KbError`, for each refusal the CLI
  makes today, with today's text:
  - a root hub with no `hub:`;
  - `intake:` on a hub-to-hub publish;
  - `--pr` together with `--direct`.
- `cli.publish` shrinks to:
  1. read flags;
  2. `plan()`;
  3. refresh `-code` when the plan says so;
  4. the unreviewed gate (not on the federation route);
  5. call the route's existing function;
  6. echo the report.
- The CLI's error text and exit codes stay byte-identical. The existing
  CLI tests are the oracle.

### 4. `doctor.run()` → issues and stale flag

- `doctor.run(kb_dir, handle, *, context_text=None) -> DoctorResult(issues, stale)`.
  It holds everything after the hub is resolved:
  - the source-dirs and credential checks;
  - the kind-specific checks;
  - the hub checks (with the upstream-identity logic);
  - the dev sync/lag checks;
  - the context check.
- `cli.doctor` keeps the early `check_kind` exit, `_refresh_dev_code`,
  `_hub_or_exit`, reading `--context`, printing, and the exit-code
  mapping:
  - 1 on any error;
  - 2 on stale;
  - otherwise "kb doctor: OK".

### 5. `.git-blame-ignore-revs`

It names #86's squash commit, the `ruff format` of the whole repo.

## Out of scope

- 3c: `codeingest/types.py`, `serving/`, `doctor/checks/*`, and the
  module-level web handlers.
- Moving every other command's logic. Only `publish` and `doctor` move
  here.

## Testing

- **The sweep test.** With the five removed from the allowlist,
  `test_every_cli_terminal_exception_joins_kb_error_or_is_allowlisted`
  must pass.
- **New guard tests.**
  - A command that raises each of the five prints one red line and exits
    1, with no traceback (it fails on `main`).
  - `typer.Exit(2)` from a command still exits 2.
- **`tests/test_publish_plan.py`.** One case per route and refusal,
  called directly.
- **`tests/test_doctor_run.py`.** Hub, dev and ba kinds, and the stale
  flag, called directly.
- The whole existing CLI suite passes unchanged as the regression oracle.

## Delivery

One PR, release **1.15.0**. Internal refactor. The user-visible change is
that the five errors can no longer escape as a traceback.
