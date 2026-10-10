# Hub read-path performance: parse YAML once and fast, never block the event loop

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §6.2 F1 and F3, §8 đợt 2 items 4 and 6 (F3 part) of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 2a of wave 2. The rest goes to 2b and 2c: F2 `sections_of`,
F4/F5 tiktoken, F6/F7 digest and worktree, F8 resolve git, F12 summarize.
**Approach:** as chosen on 2026-10-10:
- `models.load_yaml_model` parses with libyaml's `CSafeLoader`, falling
  back to `SafeLoader`.
- Parsed data is cached in a bounded LRU, keyed by
  `(mtime_ns, size, ctime_ns, ino)`. A file modified less than 2 s ago is
  never cached (git's "racy entry" rule). Each call validates a fresh model.
- Every Web/REST handler body runs off the event loop.

## Goal

Measured with `scripts/perf_web_bench.py` (new in this batch) on the
review's shape: 8 repos × 5 docs × 50 sections = 2,000 sections, 10 per
file, index revisions empty.

| | before |
|---|---|
| `load_federation` | 861–993 ms |
| `/api/docs`, `/api/docs/<doc>`, section | 792–910 ms |
| `/ui?q=` · `/ui` · `/ui/docs` · section page | 3,351 · 7,926 · 2,564 · 3,625 ms |
| `/api/health` while `/ui` is in flight | **7,927 ms** (baseline 12 ms) |

Two causes:

1. **Pure-Python YAML parsed again on every call.** `load_federation` opens
   every manifest whose index revision is empty. `uidata` parses every
   manifest again, three times for the overview page. `models.load_yaml_model`
   uses `yaml.safe_load` even though libyaml is installed. The review
   measured a 500-section manifest at 439 ms (`safe_load`), 49 ms
   (`CSafeLoader`) and 2 ms (pydantic validate).
2. **Sync work on the event loop.** Every handler except `/api/search`,
   `/ui?q=` search and static files runs on the loop. One slow page
   freezes MCP and REST for every agent.

Targets on the same bench:
- `/api/health` stays under 100 ms while any route is in flight.
- Warm `load_federation` and `/api/docs*` take at most 100 ms.
- Warm `/ui` takes at most 500 ms.

## Design

### 1. Fast, cached YAML loading (F1)

`models.py`:

```python
try:
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # PyYAML built without libyaml
    from yaml import SafeLoader as _YamlLoader

RACY_WINDOW_NS = 2_000_000_000
_YAML_CACHE_MAX = 2048
```

- **`load_yaml_data(path) -> object`.**
  - `os.stat` the path. The key is
    `(st_mtime_ns, st_size, st_ctime_ns, st_ino)` under
    `os.path.abspath(path)`.
  - On a hit, return the cached object.
  - On a miss, read and parse with `_YamlLoader`. Store the result only when
    `time.time_ns() - st_mtime_ns > RACY_WINDOW_NS`.
  - The table is an `OrderedDict` LRU behind a `threading.Lock`.
- **`load_yaml_model(path, model)`** returns
  `model.model_validate(load_yaml_data(path) or {})`. That is a new pydantic
  object every call. Pydantic v2 builds new containers for `list`/`dict`
  fields, so a caller mutating its model never touches the cached data. No
  model in `models.py` has an `Any` field that would alias it.
- **Why the racy window.** Linux file timestamps tick at about 4 ms
  (coarse clock). A same-size rewrite inside one tick would otherwise keep
  the old key, even though `ctime_ns` and `ino` usually catch it (a
  rename-replace changes the inode). Freshly written files therefore always
  re-parse. Every test that writes then reads behaves exactly as today. A
  hub checkout's files are older than 2 s on every request after the first.
- **`save_yaml_model` is unchanged** (pure-Python `safe_dump`). libyaml's
  emitter can format differently, and committed manifests must not churn.
- `clear_yaml_cache()` exists for tests.
- The 22 direct `yaml.safe_load` sites stay as they are. None is on a
  request path that runs per section.

With the cache:
- `load_federation` costs a directory walk plus one stat and one validate
  per file.
- `uidata._iter_manifests` called three times on `/ui` costs three
  validates per manifest, not three parses.
- No caller changes.

**Not done:**
- Writing `revision` into `index.yaml` (review F1 (c)). It would re-open
  the "`-code` index never churns" decision of spec 2026-09-25 §4.1, and
  the cache makes the manifest read cheap anyway.
- A per-request `FederationView` (F1 (d)) and `status_map` from
  `search.db` (F1 (e)). The cache covers both.

### 2. Handlers off the event loop (F3)

Starlette runs a plain `def` endpoint in its threadpool:

- **`web/api.py`:** `docs`, `doc_detail`, `section` and `api_search` become
  `def`. `api_search` calls `search` directly. Its `hub_handle` and
  `stale_hub_note` move off the loop with it. `health` stays `async`; it
  touches nothing.
- **`web/ui.py`:**
  - `home`, `docs_page`, `doc_page` and `section_page` become `def`.
  - `_search_screen` becomes a sync helper that `home` calls.
  - `asset` keeps `async`, but its `hub_handle` moves into the threadpool
    call alongside `_find_asset`.
  - `login_get`, `login_post`, `logout_post` and `static_file` stay as
    they are: they await the form or file and touch no hub.
- **`hub.resolve_hub`** takes a per-cache-key `threading.Lock` around the
  clone, reclone and pull branch. Concurrent requests could already reach
  it from MCP's worker threads. Moving the web handlers there makes two
  simultaneous `git pull`s on one cache likely. A local-path hub (the
  serving case `--hub /data`) returns before the lock.
- Exception handlers (`SnapshotCorruptError`) and the error-page shell see
  exceptions from a sync endpoint the same way. Starlette re-raises them on
  the loop.

### 3. Bench

`scripts/perf_web_bench.py` builds the synthetic hub, starts uvicorn on a
local port, and prints three things per route: the median latency, and the
`/api/health` latency while that route is in flight. It is manual, like
`perf_search_smoke.py`, and not a CI gate.

## Testing

- **YAML cache.**
  - A file older than the racy window is parsed once. A spy on the loader
    counts calls.
  - A rewrite with new content and an mtime set forward re-parses.
  - A file younger than 2 s re-parses every call.
  - A mutated returned model leaves the next call unaffected.
  - LRU eviction past the cap.
  - A missing file still raises `FileNotFoundError`.
  - Malformed YAML still raises `yaml.YAMLError`, and is not cached.
  - The `SafeLoader` fallback, forced by monkeypatch, yields equal models.
- **Parity.** Every YAML file under `tests/fixtures` and `templates/init`
  loads to the same data through `CSafeLoader` and `SafeLoader`.
- **Event loop.**
  - A test app whose `uidata.store_stats` is monkeypatched to sleep 1 s,
    driven through `httpx.AsyncClient` with an ASGI transport.
    `/api/health` completes in under 300 ms while `/ui` is in flight.
  - The same holds for `/api/docs`.
- **`resolve_hub` lock.** Two threads resolving one URL hub whose TTL has
  expired run `gitio.pull` once at a time (a fake pull records overlap).
- The full suite must pass, and the bench before/after goes in the PR.

## Delivery

One PR, release **1.12.0**. Behaviour is unchanged and the speed-up is
large. The CHANGELOG states the bench numbers and the 2 s racy window: a
manifest edited in place is always re-read, and one older than 2 s is
cached until its stat changes.
