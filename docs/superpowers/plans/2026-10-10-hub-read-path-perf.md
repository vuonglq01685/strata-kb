# Hub read-path performance Implementation Plan

**Goal:**
- `/api/health` (and MCP) stays responsive while any page renders.
- Warm `load_federation` and `/api/docs*` take at most 100 ms, and `/ui`
  at most 500 ms, on the 2k-section bench.

**Spec:** `docs/superpowers/specs/2026-10-10-hub-read-path-perf-design.md`

## Global constraints

- Release **1.12.0**: `pyproject.toml`, `uv.lock` and the CHANGELOG.
- Test command: `uv run pytest -q -p tikstub`. `tikstub` is the scratchpad
  stand-in for `cl100k_base`.
- Measure before and after with `scripts/perf_web_bench.py`, and put both
  in the PR.

## Deviations from the spec (decided while implementing)

- **The bench backdates every file by an hour after building the hub.** A
  served checkout's files are old. Without the backdating, every file sits
  inside the 2 s racy window and the in-process `load_federation` line
  measures only the libyaml speed-up.
- **The event-loop test** measures `/api/health` from when the probe was
  *due*, not from when its timer ran. A blocked loop delays the timer
  itself, so the first version passed on the old code too.

---

### Task 1: Bench and baseline

- [x] `scripts/perf_web_bench.py`. Baseline (2k sections):
  - `/ui` 7,926 ms, `/api/health` meanwhile 7,927 ms
  - `load_federation` 861 ms

### Task 2: Cached libyaml loading (spec §1)

- [x] `models.load_yaml_data` / `load_yaml_model` / `clear_yaml_cache`.
- [x] `tests/test_yaml_cache.py`:
  - parse once
  - fresh file re-parsed
  - same-size rewrite
  - mutation isolation
  - LRU bound
  - missing file and malformed YAML
  - libyaml vs pure-Python parity over every fixture and template YAML

### Task 3: Handlers off the event loop + resolve_hub lock (spec §2)

- [x] `web/api.py` and `web/ui.py` handlers become `def`. `asset` resolves
  the hub in the threadpool.
- [x] A per-cache lock in `hub.resolve_hub`.
- [x] `tests/test_web_event_loop.py`, which fails on the old handlers, and
  `test_concurrent_resolves_never_pull_one_cache_twice_at_once`.

### Task 4: Release

- [x] Bench after, at 2k and 10k sections.
- [x] CHANGELOG 1.12.0 and the version bump.
- [x] Full suite and ruff, then commit, push and open the PR.
