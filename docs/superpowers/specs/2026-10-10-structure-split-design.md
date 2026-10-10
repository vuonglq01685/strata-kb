# Structure: codeingest types, a neutral serving/ package, doctor as a package

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §4.2 and §8 đợt 3 item 8 (part 2) of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3c of wave 3. It follows #86 (3a, tooling) and #87 (3b, the KbError
guard and library publish/doctor).
**Constraint:** structure only. No behaviour changes, no message changes,
and the full suite passes with only import-path updates in tests.

## Goal

| Problem | Today |
|---|---|
| `codeingest.core` and its extractors import each other. | Extractors import their types from `core`, so `core` imports the registry at the bottom of the file under `# noqa: E402`. |
| `web` and `mcp` depend on each other. `intake` imports `web`. | `web/api`, `web/ui` and `web/app` import `mcp.ServerConfig`. `mcp` imports `web.auth`. `intake` imports `web.ratelimit`. |
| `doctor.py` is 1,364 lines. | It holds every check, its issue type, and `run()` in one module. |

## Design

### 1. `codeingest/types.py` and `codeingest/localgit.py`

- `types.py` holds `CodeSection`, `ExtractResult`, `CodeIngestOptions` and
  the `Extractor` protocol. Extractors import from it, never from `core`.
- `localgit.run()` is the degrade-gracefully git helper, formerly
  `core._git`. Its S603/S607 ignore moves with it.
- `core` imports the registry at the top. It re-exports the four types,
  so `core.CodeSection` and friends keep working.

### 2. `serving/`: transport-neutral

- New package `strata_kb/serving/` with:
  - `config.py`: `ServerConfig`;
  - `auth.py`, moved from `web/auth.py`;
  - `ratelimit.py`, moved from `web/ratelimit.py`.
- `mcp` imports `serving` and never `web` at module level. Its `main()`
  still builds the http app from `web.app`, the one composition point.
- `web` imports `serving` and never `mcp`.
- `intake` imports `serving.ratelimit` and never `web`.
- No shims: tests import the new paths, because a test that monkeypatches
  `ratelimit` attributes must patch the module the code reads.
- A test pins the layering:
  - `web/*` never imports `strata_kb.mcp`;
  - `intake.py` never imports `strata_kb.web`;
  - `serving/*` imports neither `web` nor `mcp`.

### 3. `doctor/` package

The checks split by concern:

| Module | Contents |
|---|---|
| `doctor/issues.py` | `Issue`, `_flatten`, `_CONFIG_READ_ERRORS` |
| `doctor/checks/local.py` | `check_kb`, `check_kind`, `check_source_dirs`, `check_config_credentials` |
| `doctor/checks/usage.py` | `check_usage_log`, `check_usage_hooks` |
| `doctor/checks/assets.py` | `check_asset_store`, `ASSET_SIZE_WARN_BYTES` |
| `doctor/checks/context.py` | `check_context` |
| `doctor/checks/hub.py` | `check_hub`, `check_published_digests`, `check_federation_publish` and their digests |
| `doctor/checks/dev.py` | `check_dev_sync`, `check_hub_lag` |
| `doctor/__init__.py` | `DoctorResult` and `run()`, plus re-exports of every name callers use today |

Every existing `from strata_kb.doctor import X` keeps working.

## Out of scope

- 3d: one template body per skill.
- 3e: item 11, plus item 10's docstrings and provenance comments.
- Module-level web handlers with a `Context` dataclass. The review lists it
  under refactor (4). It changes the handler shape, not only where code
  lives, so it needs its own design.

## Testing

- The full suite, with only import-path updates.
- `test_codeingest_imports_in_any_order`: four entry modules, each in a
  fresh interpreter.
- `test_core_has_no_deferred_imports`.
- A layering test for `serving`, `web`, `mcp` and `intake`.

## Delivery

One PR, release **1.15.1**: internal structure, no behaviour change.
