# Search / MCP / kb-context Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MCP tool surface actually answer, make the search index reflect the hub it indexes, and remove every path where an agent asks for one thing and silently receives another.

**Architecture:** Three independent seams. (1) The native `sqlite_vec`/numpy import moves out of the request path into a one-shot warm-up called before any event loop starts, and the five MCP tools plus the two `async def` web search paths run their blocking bodies on a worker thread. (2) `searchdb` learns to tell a caller's mistake (`IntegrityError`, over-long bind list) from real corruption, serialises the cold build, and fingerprints the whole federation entry directory by stat rather than by two small files. (3) `query.search` grows a notes channel that both surfaces render, carrying the truncation, ambiguity, unknown-tag and empty-token signals the contract promises; `query.get_section` grows a single `normalize_level` choke point; `resolve` promotes "the cited thing no longer exists" from `stale` to `broken`.

**Tech Stack:** Python 3.11+, `sqlite3` + FTS5 + `sqlite-vec`, `mcp` (FastMCP), `anyio`, Starlette, Typer, pytest + `anyio` plugin.

**Spec:** `docs/superpowers/specs/2026-09-10-search-mcp-context-review-fixes-design.md`

## Global Constraints

- **Golden MCP schema is frozen.** `tests-gate/golden/mcp_tools.json` is compared byte-identical. FastMCP derives every tool schema from the function signature plus `__doc__` (`_canonical_docstring`, `src/center_kb/mcp.py:72-86`). Parameter names, annotations, defaults and docstrings change **only** in Task 16, which regenerates the golden deliberately.
- **Exactly three resolve statuses.** `ok` / `stale` / `broken` with exits `0` / `2` / `1`. No fourth status, ever (C8).
- **`K_LEG = 50` and `RRF_K = 60` are unchanged** (`src/center_kb/searchdb.py:29-30`). This batch reports the leg cap, it does not raise it.
- **No re-ingest, no re-summarize.** The bundled `.kb/` is not touched. The search index rebuilds itself.
- **Windows is the primary platform.** Never `unlink` a file another process may hold without the force path; never let `PermissionError` or a rich traceback reach the user.
- **Run tests with the repo venv:** `.venv/Scripts/python -m pytest <path> -v`. The venv is uv-managed — do **not** run `pip`.
- **The full suite takes 10–19 minutes.** Run only the named test file(s) per task. The whole suite runs once, in Task 16.
- **Shell:** commands are written for the Bash tool (`VAR=value cmd`). In PowerShell set the variable first: `$env:KB_VENV = "$PWD\.venv"`.
- Out of scope, do not implement: F-C8 code changes (README sentence only), F-C11, F-C12, F-C15, F-C16.

---

### Task 1: `warm_vec()` — take the native import off the event loop (F-C1)

**Files:**
- Create: `tests/test_mcp_stdio.py`
- Modify: `src/center_kb/searchdb.py:74-90` (`_load_vec`)
- Modify: `src/center_kb/mcp.py:89` (`create_server`)
- Modify: `src/center_kb/web/app.py:14` (`create_app`)

**Interfaces:**
- Consumes: nothing.
- Produces: `searchdb.warm_vec() -> bool` — imports `sqlite_vec` once, caches the module or the failure, never raises, safe to call repeatedly.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_stdio.py`:

```python
"""kb_search over real stdio must answer.

Reviewer C F-C1: `searchdb._load_vec` imported `sqlite_vec` — and transitively
numpy's native `_multiarray_umath` — at request time, and FastMCP runs a sync
tool inline on the asyncio event-loop thread, where that native import
deadlocks on Windows. The server stayed alive and never replied: 120 s, no
response, ever. Every `[embed]` install, every `[dev]` install and this repo's
own `.venv` is affected.

The reader runs on its own thread so that a hang fails this test instead of
hanging it.
"""
import json
import queue
import subprocess
import sys
import threading
import time

import pytest

pytest.importorskip("sqlite_vec")  # the deadlock only exists when it is importable

TIMEOUT_S = 30


def _reader(pipe, q: "queue.Queue") -> None:
    for line in pipe:
        q.put(line)
    q.put(None)


def _send(proc, payload: dict) -> None:
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def test_kb_search_over_stdio_answers(fed_hub):
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "center_kb.mcp",
            "--kb", str(fed_hub / ".kb"),
            "--hub", str(fed_hub),
            "--transport", "stdio",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()
    try:
        _send(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-test", "version": "0"},
            },
        })
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _send(proc, {
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "kb_search", "arguments": {"query": "airspace"}},
        })
        deadline = time.monotonic() + TIMEOUT_S
        while True:
            remaining = deadline - time.monotonic()
            assert remaining > 0, (
                f"kb_search did not answer within {TIMEOUT_S}s over stdio "
                "(F-C1: native import deadlocked on the event-loop thread)"
            )
            try:
                line = q.get(timeout=remaining)
            except queue.Empty:
                raise AssertionError(
                    f"kb_search did not answer within {TIMEOUT_S}s over stdio "
                    "(F-C1: native import deadlocked on the event-loop thread)"
                )
            assert line is not None, "server closed stdout before answering"
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                assert "result" in msg, msg
                return
    finally:
        proc.kill()
        proc.wait(timeout=10)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mcp_stdio.py -v`

Expected on Windows with `sqlite-vec` installed: FAIL with `kb_search did not answer within 30s over stdio`. On a platform where the native import does not deadlock the test may already pass — that is fine, it is still the regression guard; note which you observed in the commit message.

- [ ] **Step 3: Add `warm_vec()` and make `_load_vec` use it**

In `src/center_kb/searchdb.py`, replace `_load_vec` (lines 74-90) with:

```python
_VEC_MODULE = None
_VEC_WARMED = False


def warm_vec() -> bool:
    """Import sqlite_vec exactly once, off any event loop. Never raises.

    Reviewer C F-C1: this import pulls numpy's native `_multiarray_umath`, and
    doing it inside a tool call that FastMCP runs inline on the asyncio
    event-loop thread deadlocks on Windows — the server stays alive and never
    answers. Every entry point that owns an event loop calls this before the
    loop starts; the CLI does not, so `kb` keeps its startup time."""
    global _VEC_MODULE, _VEC_WARMED
    if _VEC_WARMED:
        return _VEC_MODULE is not None
    try:
        import sqlite_vec
    except ImportError:
        _VEC_MODULE = None
    else:
        _VEC_MODULE = sqlite_vec
    _VEC_WARMED = True
    return _VEC_MODULE is not None


def _load_vec(conn: sqlite3.Connection) -> bool:
    if not warm_vec():
        return False
    try:
        conn.enable_load_extension(True)
        try:
            _VEC_MODULE.load(conn)
        finally:
            conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        # Python build lacks loadable-extension support / extension failed to
        # load → degrade to FTS-only instead of breaking search entirely (spec §5)
        logger.warning("sqlite-vec could not be loaded — semantic leg disabled: %s", exc)
        return False
    return True
```

- [ ] **Step 4: Warm at both entry points that own a loop**

In `src/center_kb/mcp.py`, make `create_server` start with the warm-up:

```python
def create_server(config: ServerConfig) -> MCPServer:
    from center_kb import searchdb

    # F-C1: never import sqlite_vec/numpy from inside a tool call — FastMCP runs
    # sync tools on the event-loop thread and the native import deadlocks there.
    searchdb.warm_vec()
    mcp = MCPServer("center-kb")
```

In `src/center_kb/web/app.py`, make `create_app` start with the same two lines, immediately after the docstring:

```python
def create_app(config: ServerConfig, token: str, mcp_server=None, intake_cfg=None):
    """<docstring unchanged>"""
    from center_kb import searchdb

    # F-C1, same reason as mcp.create_server. NOT in `lifespan`: line 36 leaves
    # lifespan None when mcp_server is None, so the API-only app would skip it.
    searchdb.warm_vec()

    async def root(request: Request) -> RedirectResponse:
```

- [ ] **Step 5: Add the wiring test**

Append to `tests/test_mcp.py`:

```python
def test_create_server_warms_the_native_import(fed_hub, monkeypatch):
    """F-C1: the warm-up must happen while create_server runs (no loop yet),
    not on the first tool call (on the loop)."""
    from center_kb import mcp as mcp_mod
    from center_kb import searchdb

    calls = []
    monkeypatch.setattr(searchdb, "warm_vec", lambda: (calls.append(1), True)[1])
    mcp_mod.create_server(_config(fed_hub))
    assert calls == [1]
```

- [ ] **Step 6: Run both tests**

Run: `.venv/Scripts/python -m pytest tests/test_mcp_stdio.py tests/test_mcp.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add tests/test_mcp_stdio.py tests/test_mcp.py src/center_kb/searchdb.py src/center_kb/mcp.py src/center_kb/web/app.py
git commit -m "fix(mcp): warm the sqlite_vec import off the event loop (F-C1)"
```

---

### Task 2: Run tool bodies off the event loop (F-C1, second layer)

**Files:**
- Modify: `src/center_kb/mcp.py:103-220` (all five tools)
- Modify: `src/center_kb/web/api.py:147` (`api_search`)
- Modify: `src/center_kb/web/ui.py:236` (`_search_screen`)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `searchdb.warm_vec()` from Task 1.
- Produces: the five tools are now `async def` with byte-identical signatures and docstrings. Callers reach them only through the MCP session, so nothing else changes.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp.py` (the file already has the `anyio_backend` fixture and `connect_client`):

```python
@pytest.mark.anyio
async def test_tool_body_does_not_block_the_event_loop(fed_hub, monkeypatch):
    """F-C1, second layer: a sync tool body run inline on the loop starves
    every other task. With the body on a worker thread the loop keeps ticking."""
    import asyncio
    import time as _time

    from center_kb import mcp as mcp_mod

    def slow_search(*args, **kwargs):
        _time.sleep(0.5)
        return []

    monkeypatch.setattr(mcp_mod, "search", slow_search)
    server = create_server(_config(fed_hub))
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async with connect_client(server, raise_exceptions=True) as client:
        hb = asyncio.create_task(heartbeat())
        await client.call_tool("kb_search", {"query": "airspace"})
        hb.cancel()
    assert ticks >= 5, f"event loop was starved during the tool call (ticks={ticks})"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_mcp.py::test_tool_body_does_not_block_the_event_loop -v`
Expected: FAIL — `event loop was starved during the tool call (ticks=0)`.

- [ ] **Step 3: Move each tool body onto a worker thread**

In `src/center_kb/mcp.py`, add `import anyio.to_thread` to the imports at the top, then convert each of the five tools to this shape. `kb_search` in full — the docstring, parameter names, annotations and defaults are **unchanged**:

```python
    @mcp.tool()
    @_canonical_docstring
    async def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Find sections by hybrid search (FTS5 keyword + semantic KNN, RRF-fused);
        return L2 content within the token budget, with citations. Returns
        every relevant section found, not just the best match — when using
        this to draft a User Story, show ALL returned sections (with their
        citations) to the user and confirm which ones actually apply before
        writing story content from them. Citing more than one section for a
        single story is normal. Once confirmed, call kb_context_new with the
        confirmed refs to pin them for the ticket. Results come from the hub
        federation — unpublished local content never appears."""

        def _run() -> str:
            hub = _hub()
            if hub is None:
                return HUB_DOWN
            results = search(hub, query, tags=tags, budget=budget)
            if not results:
                return "No matching section found — try dropping tags or changing keywords."
            note = _stale_note(hub) + _ambiguity_note(results)
            return note + "\n\n".join(
                f"--- [{r.citation}] match={r.match_mode} ~{r.tokens}tk\n{r.content}"
                + (f"\nraw match: {r.snippet}" if r.snippet else "")
                for r in results
            )

        return await anyio.to_thread.run_sync(_run)
```

Apply the identical transformation to `kb_get_section`, `kb_context_new`, `kb_resolve` and `kb_ticket_lint`: prefix the `def` with `async`, wrap the existing body verbatim in a nested `def _run() -> str:`, and end with `return await anyio.to_thread.run_sync(_run)`. Do not touch a single character of any docstring or parameter list.

- [ ] **Step 4: Move the two web search paths off the loop**

In `src/center_kb/web/api.py`, add `from starlette.concurrency import run_in_threadpool` to the imports and change the one call in `api_search`:

```python
        results = await run_in_threadpool(
            search, hub, q, tags=tags, budget=budget
        )
```

In `src/center_kb/web/ui.py`, add the same import and change the call in `_search_screen`:

```python
        found = (
            await run_in_threadpool(
                search, hub, q, tags=tags or None, budget=budget,
                use_semantic=use_semantic,
            )
            if q else []
        )
```

- [ ] **Step 5: Run the MCP, web and stdio tests**

Run: `.venv/Scripts/python -m pytest tests/test_mcp.py tests/test_mcp_http.py tests/test_web_api.py tests/test_web_ui.py tests/test_mcp_stdio.py -v`
Expected: PASS, including `test_core_four_tool_signatures_unchanged` and `test_lists_exactly_five_tools` — proof the wire contract survived.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/mcp.py src/center_kb/web/api.py src/center_kb/web/ui.py tests/test_mcp.py
git commit -m "fix(mcp,web): run blocking search bodies off the event loop (F-C1)"
```

---

### Task 3: Tell a caller's mistake from corruption (F-C2, F-C10)

**Files:**
- Modify: `src/center_kb/searchdb.py` (add after `is_lock_error`, line 103)
- Modify: `src/center_kb/query.py:125-132`
- Test: `tests/test_searchdb.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `searchdb.classify_db_error(exc: sqlite3.Error) -> str` returning `"lock"`, `"client"` or `"corrupt"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_searchdb.py`:

```python
@pytest.mark.parametrize(
    "exc, expected",
    [
        (
            sqlite3.IntegrityError(
                "UNIQUE constraint failed: sections.repo_id, sections.doc_id, "
                "sections.section_id"
            ),
            "client",
        ),
        (sqlite3.OperationalError("too many SQL variables"), "client"),
        (sqlite3.OperationalError("database is locked"), "lock"),
        (sqlite3.DatabaseError("database disk image is malformed"), "corrupt"),
    ],
)
def test_classify_db_error(exc, expected):
    """F-C2/F-C10: a lost UNIQUE race and an over-long bind list are the
    CALLER's problem. Treating them as corruption deleted the index every user
    of that hub shares."""
    assert searchdb.classify_db_error(exc) == expected


def test_client_error_never_deletes_the_index(fed_hub, monkeypatch):
    from center_kb import query as query_mod
    from center_kb.hub import HubHandle

    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    db = searchdb.db_path(hub)
    assert db.exists()

    def boom(*args, **kwargs):
        raise sqlite3.IntegrityError(
            "UNIQUE constraint failed: sections.repo_id, sections.doc_id, "
            "sections.section_id"
        )

    monkeypatch.setattr(searchdb, "open_fresh", boom)
    with pytest.raises(sqlite3.IntegrityError):
        query_mod.search(hub, "airspace")
    assert db.exists(), "a caller's IntegrityError deleted the shared index"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb.py -k "classify or never_deletes" -v`
Expected: FAIL — `classify_db_error` does not exist; and once it does, `test_client_error_never_deletes_the_index` still fails on `db.exists()`.

- [ ] **Step 3: Add the classifier**

In `src/center_kb/searchdb.py`, directly after `is_lock_error` (ends line 103):

```python
def classify_db_error(exc: sqlite3.Error) -> str:
    """'lock' | 'client' | 'corrupt' — what to do about a sqlite error.

    Reviewer C F-C2/F-C10: `IntegrityError` (a lost UNIQUE race between two
    cold builds) and `OperationalError: too many SQL variables` (an oversized
    client-supplied `tags` list) are both CALLER problems. They were diagnosed
    as corruption, so the index every user of the hub shares was deleted — and
    on Windows the unlink then raised PermissionError in the user's face."""
    if is_lock_error(exc):
        return "lock"
    if isinstance(exc, sqlite3.IntegrityError):
        return "client"
    if isinstance(exc, sqlite3.OperationalError) and (
        "too many sql variables" in str(exc).lower()
    ):
        return "client"
    return "corrupt"
```

- [ ] **Step 4: Only rebuild on real corruption**

In `src/center_kb/query.py`, replace the `except sqlite3.DatabaseError` branch of `_search_index` (lines 125-132) with:

```python
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()  # Windows: close before unlink
                conn = None
            kind = searchdb.classify_db_error(exc)
            if kind != "corrupt" or attempt == 2:
                # lock = another process is writing; client = the caller's own
                # input. Neither is a reason to delete the shared index (F-C2).
                raise
            logger.warning("search.db corrupt — rebuilding once: %s", exc)
            searchdb.delete_db(hub)
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb.py tests/test_query.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/searchdb.py src/center_kb/query.py tests/test_searchdb.py
git commit -m "fix(searchdb): never delete the index for a caller's error (F-C2, F-C10)"
```

---

### Task 4: Make losing the cold-build race harmless (F-C2)

**Files:**
- Create: `tests/test_searchdb_concurrency.py`
- Modify: `src/center_kb/hashsync.py:53` (rename `_unlink_force` → `unlink_force`, update lines 69 and 74)
- Modify: `src/center_kb/searchdb.py:166-172` (`delete_db`), `:468-483` (the per-repo loop in `_sync_conn`)
- Modify: `src/center_kb/cli.py` (`query` and `reindex` commands — clean exit on a busy index)

**Interfaces:**
- Consumes: `searchdb.classify_db_error` from Task 3.
- Produces: `hashsync.unlink_force(path: Path) -> None`; `searchdb.IndexBusyError(RuntimeError)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_searchdb_concurrency.py`:

```python
"""Cold-build concurrency.

Reviewer C F-C2: five `kb query` processes against a hub with no search.db —
the normal state after a fresh clone, or several agents starting at once —
gave 3/5 failures on EVERY trial, each with a raw rich traceback:

    search.db corrupt — rebuilding once: UNIQUE constraint failed: ...
    PermissionError: [WinError 32] The process cannot access the file ...

`searchdb.py:322-336` claims "losing the race must be idempotent and must not
break UNIQUE"; this test is that claim.
"""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("sqlite_vec")

# No `__main__` module in the package: reach the Typer app directly.
_KB = [sys.executable, "-c", "from center_kb.cli import app; app()"]


def _run_query(fed_hub) -> subprocess.CompletedProcess:
    return subprocess.run(
        _KB + [
            "query", "airspace",
            "--hub", str(fed_hub),
            "--kb-dir", str(fed_hub / ".kb"),
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


def test_five_concurrent_cold_builds_all_succeed(fed_hub):
    db = fed_hub / ".kb-work" / "search.db"
    for p in (db, Path(f"{db}-wal"), Path(f"{db}-shm")):
        p.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=5) as pool:
        procs = list(pool.map(lambda _: _run_query(fed_hub), range(5)))

    failures = [p for p in procs if p.returncode != 0]
    assert not failures, "\n\n".join(
        f"exit {p.returncode}\n{p.stderr}" for p in failures
    )
    assert not any("Traceback" in p.stderr for p in procs)
    assert not any("UNIQUE constraint failed" in p.stderr for p in procs)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb_concurrency.py -v`
Expected: FAIL — some processes exit non-zero with `UNIQUE constraint failed` and/or `PermissionError` in stderr.

- [ ] **Step 3: Promote the force-unlink helper**

In `src/center_kb/hashsync.py`, rename `_unlink_force` to `unlink_force` (line 53) and update its two call sites (lines 69 and 74). Nothing else in `src/` references the old name — confirm with `grep -rn "_unlink_force" src/ tests/` before committing.

- [ ] **Step 4: Make `delete_db` survive a held file**

In `src/center_kb/searchdb.py`, add the exception type next to the other module-level definitions (after `logger`, line 25) and rewrite `delete_db`:

```python
class IndexBusyError(RuntimeError):
    """The index file is held by another process and could not be replaced."""
```

```python
def delete_db(hub: "HubHandle") -> None:
    """Delete the index file (plus -wal/-shm). The caller must close every
    connection first (Windows cannot unlink an open file — spec windows-support
    §R5).

    Reviewer C F-C2: a bare `unlink()` raised `PermissionError [WinError 32]`
    straight at the user when another process still held the file. hashsync's
    force-unlink (chmod +w, retry) exists for exactly this case; a file still
    held after it becomes a clean IndexBusyError, never a traceback."""
    from center_kb import hashsync

    path = db_path(hub)
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if not p.exists():
            continue
        try:
            hashsync.unlink_force(p)
        except PermissionError as exc:
            raise IndexBusyError(
                f"search index {p.name} is in use by another process — "
                "close other kb commands and retry"
            ) from exc
```

- [ ] **Step 5: Serialise the per-repo write phase**

In `src/center_kb/searchdb.py`, in `_sync_conn`, replace the head of the per-repo loop. Today `stored_fp` is read once, before any lock, so two cold processes both decide the repo needs syncing and the loser hits UNIQUE. Re-read the fingerprint **under the write lock**:

```python
    for repo in repos:
        fp = _repo_fingerprint(repo.kb_dir)
        if stored_fp.get(repo.meta.repo_id) == fp:
            continue  # repo unchanged — 0 manifest parses
        # F-C2: `stored_fp` was read outside any lock, so two cold processes
        # both got here and the loser broke UNIQUE. Take the write lock FIRST,
        # then re-read this repo's fingerprint inside it: the loser now sees
        # the winner's row and skips instead of inserting (spec §5 — losing the
        # race only wastes work, never corrupts data).
        if conn.in_transaction:
            conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT fingerprint FROM repos WHERE repo_id = ?",
            (repo.meta.repo_id,),
        ).fetchone()
        if row is not None and row[0] == fp:
            conn.commit()
            continue
        before_updated = report.sections_updated
        _sync_repo(conn, repo, report)
```

The rest of the loop body (the `INSERT INTO repos ... ON CONFLICT`, the `vec_coverage` write and the trailing `conn.commit()`) is unchanged.

- [ ] **Step 6: Surface `IndexBusyError` cleanly in the CLI**

In `src/center_kb/cli.py`, in the `query` command, wrap the search call:

```python
    from center_kb import searchdb

    try:
        results = search(
            handle, text, tags=tag_list, budget=budget, semantic=semantic
        )
    except searchdb.IndexBusyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

In the `reindex` command, wrap `searchdb.sync(handle, default_embedder())` the same way.

- [ ] **Step 7: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb_concurrency.py tests/test_searchdb.py tests/test_hashsync.py tests/test_cli.py -v`
Expected: PASS — five exit 0, no traceback, no `UNIQUE constraint failed`.

- [ ] **Step 8: Commit**

```bash
git add tests/test_searchdb_concurrency.py src/center_kb/hashsync.py src/center_kb/searchdb.py src/center_kb/cli.py
git commit -m "fix(searchdb): serialise the cold build and force-unlink on Windows (F-C2)"
```

---

### Task 5: Cap the client-supplied tag list (F-C10)

**Files:**
- Modify: `src/center_kb/searchdb.py:541` (`_norm_tags`), add `MAX_TAGS` next to `K_LEG` (line 29)
- Test: `tests/test_searchdb.py`

**Interfaces:**
- Consumes: `searchdb.classify_db_error` (Task 3) for the "index survives" half of the test.
- Produces: `searchdb.MAX_TAGS = 100`; `_norm_tags` raises `ValueError` above it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_searchdb.py`:

```python
def test_oversized_tag_list_is_refused_and_the_index_survives(fed_hub):
    """F-C10: `tags` reached `IN (?,?,…)` with no cap, so 40 000 entries gave
    `too many SQL variables` — an OperationalError that was read as corruption,
    and `delete_db()` destroyed the index shared by every user of that hub.
    `tags` is agent-supplied on the MCP tool, so a malformed call reached it."""
    from center_kb import query as query_mod
    from center_kb.hub import HubHandle

    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    db = searchdb.db_path(hub)
    assert db.exists()

    with pytest.raises(ValueError) as excinfo:
        query_mod.search(hub, "airspace", tags=[f"t{i}" for i in range(40_000)])
    assert "too many tags" in str(excinfo.value)
    assert db.exists(), "a caller's oversized tag list deleted the shared index"


def test_tag_list_at_the_cap_is_accepted(fed_hub):
    from center_kb import query as query_mod
    from center_kb.hub import HubHandle

    hub = HubHandle(root=fed_hub)
    tags = [f"t{i}" for i in range(searchdb.MAX_TAGS - 1)] + ["arinc424"]
    assert query_mod.search(hub, "airspace", tags=tags)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb.py -k "tag_list" -v`
Expected: FAIL — `MAX_TAGS` does not exist.

- [ ] **Step 3: Add the cap**

In `src/center_kb/searchdb.py`, beside `K_LEG` (line 29):

```python
MAX_TAGS = 100  # F-C10: `tags` is agent-supplied and expands to one SQL bind each
```

and rewrite `_norm_tags`:

```python
def _norm_tags(tags: list[str] | None) -> list[str]:
    out = sorted({t.strip().lower() for t in tags or [] if t.strip()})
    if len(out) > MAX_TAGS:
        # Refuse, do not truncate: a silently shortened filter returns results
        # the caller did not ask for. The published federation vocabulary is a
        # handful of tags, so no real caller meets this cap (F-C10).
        raise ValueError(
            f"too many tags ({len(out)}) — at most {MAX_TAGS} are accepted"
        )
    return out
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb.py tests/test_query.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/searchdb.py tests/test_searchdb.py
git commit -m "fix(searchdb): cap the client-supplied tag list (F-C10)"
```

---

### Task 6: Freshness key covers what it indexes, plus `kb reindex --force` (F-C3)

**Files:**
- Create: `tests/test_query_freshness.py`
- Modify: `src/center_kb/searchdb.py:226-230` (`_repo_fingerprint`)
- Modify: `src/center_kb/cli.py:1598` (`reindex`)

**Interfaces:**
- Consumes: `searchdb.delete_db` and `searchdb.IndexBusyError` from Task 4.
- Produces: `kb reindex --force`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_query_freshness.py`:

```python
"""Index freshness.

Reviewer C F-C3: `_repo_fingerprint` hashed only `_meta.yaml` and `index.yaml`,
and `_meta.yaml` is rewritten only when a CHILD publishes. So a fix made
directly in `federation/` on the hub — README §7.9 calls that "the single
review gate" — never invalidated the index. `kb query` and `kb get`
disagreed about the same section forever, and neither `kb reindex` nor
`kb doctor` repaired it; only `rm hub/.kb-work/search.db` did.
"""
import pytest
from typer.testing import CliRunner

pytest.importorskip("sqlite_vec")

from center_kb import searchdb  # noqa: E402
from center_kb.cli import app  # noqa: E402
from center_kb.hub import HubHandle  # noqa: E402
from center_kb.query import get_section, search  # noqa: E402

MARKER = "ZZHUBFIXMARKERZZ"


def test_hub_side_edit_is_visible_to_the_next_query(fed_hub, run_git):
    hub = HubHandle(root=fed_hub)
    assert search(hub, MARKER) == []          # builds the index

    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + f"\n{MARKER} typo fixed on the hub.\n",
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "reviewer fixes a typo directly on the hub")

    results = search(hub, MARKER)
    assert results, "a hub-side edit is invisible to search"
    assert results[0].section_id == "5.3"
    # and the two read paths agree
    assert MARKER in get_section(hub, "arinc-kb:arinc-424", "5.3").content


def test_reindex_force_rebuilds_from_scratch(fed_hub):
    hub = HubHandle(root=fed_hub)
    searchdb.sync(hub, None)
    conn = searchdb.open_db(hub)
    try:
        conn.execute("DELETE FROM sections")
        conn.execute("DELETE FROM fts")
        conn.commit()
    finally:
        conn.close()

    # the fingerprints still match, so an ordinary sync sees nothing to do
    searchdb.sync(hub, None)
    assert search(hub, "restrictive airspace") == []

    result = CliRunner().invoke(
        app,
        ["reindex", "--force", "--hub", str(fed_hub),
         "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 0, result.output
    assert search(hub, "restrictive airspace")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_query_freshness.py -v`
Expected: FAIL — the hub-side edit is invisible; `--force` is not a known option.

- [ ] **Step 3: Fingerprint the whole entry directory by stat**

In `src/center_kb/searchdb.py`, replace `_repo_fingerprint` (lines 226-230):

```python
def _repo_fingerprint(repo_dir: Path) -> str:
    """Stat manifest of the whole federation entry directory.

    Reviewer C F-C3: hashing only `_meta.yaml` and `index.yaml` made an edit
    committed directly in `federation/` on the hub invisible to search forever,
    while `kb get` returned it.

    Stat, don't read: this runs on EVERY query, so its cost must not scale with
    corpus bytes. (relpath, size, mtime_ns) catches both committed and
    uncommitted hub-side edits; `kb reindex --force` is the escape hatch for
    the theoretical edit that preserves all three."""
    h = hashlib.sha256()
    if not repo_dir.is_dir():
        return h.hexdigest()
    for p in sorted(repo_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        st = p.stat()
        rel = p.relative_to(repo_dir).as_posix()
        h.update(f"{rel}\0{st.st_size}\0{st.st_mtime_ns}\0".encode("utf-8"))
    return h.hexdigest()
```

- [ ] **Step 4: Add `kb reindex --force`**

In `src/center_kb/cli.py`, add the option to `reindex` (after `kb_dir`):

```python
    force: bool = typer.Option(
        False, "--force",
        help="Drop the search index and rebuild it from scratch",
    ),
```

and, in the body, immediately before `sreport = searchdb.sync(...)`:

```python
    if force:
        searchdb.delete_db(handle)
        typer.echo("kb reindex: search index dropped — rebuilding from scratch")
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_query_freshness.py tests/test_searchdb.py tests/test_query.py tests/test_cli_hub.py -v`
Expected: PASS.

- [ ] **Step 6: Measure the new fingerprint cost and record it**

Run this on the repo's own `.kb/` and put the two numbers in the commit message — the spec requires the cost of a per-query check to be measured, not assumed:

```bash
.venv/Scripts/python -c "
import statistics, time, tempfile, shutil
from pathlib import Path
from center_kb import searchdb
src = Path('.kb')
with tempfile.TemporaryDirectory() as tmp:
    entry = Path(tmp) / 'aero'
    shutil.copytree(src, entry)
    n = sum(1 for p in entry.rglob('*') if p.is_file())
    samples = []
    for _ in range(20):
        t0 = time.perf_counter()
        searchdb._repo_fingerprint(entry)
        samples.append((time.perf_counter() - t0) * 1000)
    print(f'{n} files, median {statistics.median(samples):.2f} ms')
"
```

If the median exceeds 20 ms (i.e. it would roughly double the 21 ms warm query reviewer C measured), stop and report it rather than shipping — the spec's decision 4 chose stat precisely to avoid that.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/searchdb.py src/center_kb/cli.py tests/test_query_freshness.py
git commit -m "fix(searchdb): fingerprint the whole entry dir; add kb reindex --force (F-C3)"
```

---

### Task 7: One `normalize_level` for every surface (F-C4)

**Files:**
- Create: `tests/test_query_level.py`
- Modify: `src/center_kb/query.py` (add `normalize_level`, call it in `get_section`)
- Modify: `src/center_kb/cli.py` (`get` command)
- Modify: `src/center_kb/mcp.py:138-139`

**Interfaces:**
- Consumes: nothing.
- Produces: `query.InvalidLevelError(ValueError)`; `query.normalize_level(value: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_level.py`:

```python
"""`--level` validation.

Reviewer C F-C4: `query.py:261` was `suffix = ".raw.md" if level == "l3" else
".md"` and the CLI validated nothing, so `--level L3`, `verbatim`, `raw` and
`l1` all returned the AI-condensed L2 — under a byte-identical header, so the
caller could not tell. Measured on §5.129: l3 = 1310 bytes, everything else
1219. The MCP tool did validate, so the two surfaces disagreed.
"""
import pytest
from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.hub import HubHandle
from center_kb.query import InvalidLevelError, get_section

VALID = ["l2", "l3", "L2", "L3"]
INVALID = ["verbatim", "raw", "l1", "L1", "", "  "]


@pytest.mark.parametrize("level", INVALID)
def test_get_section_refuses_an_invalid_level(fed_hub, level):
    with pytest.raises(InvalidLevelError) as excinfo:
        get_section(HubHandle(root=fed_hub), "arinc-kb:arinc-424", "5.3", level=level)
    assert "use 'l2' or 'l3'" in str(excinfo.value)


@pytest.mark.parametrize("level", VALID)
def test_get_section_accepts_either_case(fed_hub, level):
    result = get_section(
        HubHandle(root=fed_hub), "arinc-kb:arinc-424", "5.3", level=level
    )
    assert result is not None
    expected = "Verbatim" if level.lower() == "l3" else "Condensed"
    assert expected in result.content


@pytest.mark.parametrize("level", INVALID)
def test_cli_get_exits_1_on_an_invalid_level(fed_hub, level):
    result = CliRunner().invoke(
        app,
        ["get", "arinc-kb:arinc-424", "5.3", "--level", level,
         "--hub", str(fed_hub), "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 1
    assert "use 'l2' or 'l3'" in result.output


def test_cli_get_l3_returns_the_verbatim_text(fed_hub):
    result = CliRunner().invoke(
        app,
        ["get", "arinc-kb:arinc-424", "5.3", "--level", "l3",
         "--hub", str(fed_hub), "--kb-dir", str(fed_hub / ".kb")],
    )
    assert result.exit_code == 0
    assert "Verbatim" in result.output
```

And append to `tests/test_mcp.py`:

```python
@pytest.mark.anyio
async def test_kb_get_section_level_validation(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        bad = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-kb:arinc-424", "section": "5.3", "level": "verbatim"},
        )
        assert "level 'verbatim' is invalid — use 'l2' or 'l3'." in _text(bad)
        good = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-kb:arinc-424", "section": "5.3", "level": "L3"},
        )
        assert "Verbatim" in _text(good)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_query_level.py tests/test_mcp.py -k level -v`
Expected: FAIL — `InvalidLevelError` does not exist; the CLI exits 0 and returns L2 for `--level L3`.

- [ ] **Step 3: Add the single choke point**

In `src/center_kb/query.py`, beside `AmbiguousDocError`:

```python
class InvalidLevelError(ValueError):
    """`level` was neither 'l2' nor 'l3'."""


def normalize_level(value: str) -> str:
    """'l2' | 'l3', case-insensitive; anything else raises.

    Reviewer C F-C4: two surfaces disagreeing about what a level means is the
    bug — the MCP tool validated, the CLI did not, and a caller asking for the
    untouched original silently received the AI-condensed text. One function
    both call is the fix."""
    norm = (value or "").strip().lower()
    if norm not in ("l2", "l3"):
        raise InvalidLevelError(f"level '{value}' is invalid — use 'l2' or 'l3'.")
    return norm
```

and make `get_section` normalise before it does anything else:

```python
def get_section(
    hub: "HubHandle",
    doc_id: str,
    section_id: str,
    level: str = "l2",
    repo: str | None = None,
) -> QueryResult | None:
    from center_kb.federation import load_federation

    level = normalize_level(level)
    section_id = section_id.lstrip("§")
```

Everything downstream (`_get_section_in`, `_folded_result`, the `".raw.md" if level == "l3"` line at 261) now only ever sees a normalised value; leave those lines alone.

- [ ] **Step 4: Map the error at both surfaces**

In `src/center_kb/cli.py`, the `get` command:

```python
    from center_kb.query import AmbiguousDocError, InvalidLevelError, get_section

    handle = _hub_or_exit(hub, kb_dir)
    try:
        result = get_section(handle, doc_id, section, level=level, repo=repo or None)
    except InvalidLevelError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    except AmbiguousDocError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

In `src/center_kb/mcp.py`, inside `kb_get_section`'s `_run()`, delete the two-line `if level not in ("l2", "l3")` guard and catch instead — the message is byte-identical to today's, so no golden moves:

```python
        def _run() -> str:
            hub = _hub()
            if hub is None:
                return HUB_DOWN
            from center_kb.query import AmbiguousDocError, InvalidLevelError

            try:
                result = get_section(hub, doc, section, level=level, repo=repo or None)
            except InvalidLevelError as exc:
                return str(exc)
            except AmbiguousDocError as exc:
                return str(exc)
```

`src/center_kb/web/api.py:118-119` keeps its own fast 400 guard — it is already correct, and `get_section` now backstops it.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_query_level.py tests/test_query.py tests/test_mcp.py tests/test_web_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/query.py src/center_kb/cli.py src/center_kb/mcp.py tests/test_query_level.py tests/test_mcp.py
git commit -m "fix(query): validate --level in one place, both surfaces (F-C4)"
```

---

### Task 8: A notes channel, and a tokenizer symmetric with `unicode61` (F-C9)

**Files:**
- Create: `tests/test_searchdb_tokenize.py`
- Modify: `src/center_kb/searchdb.py:533-538` (`tokenize`)
- Modify: `src/center_kb/query.py` (add `SearchOutcome` + `search_detailed`; `search` becomes a wrapper)
- Modify: `src/center_kb/cli.py` (`query` renders notes on stderr)
- Modify: `src/center_kb/mcp.py` (`kb_search` renders notes in-band)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `query.SearchOutcome` — dataclass with `results: list[QueryResult]` and `notes: list[str]`.
  - `query.search_detailed(hub, text, tags=None, budget=2000, semantic=False, use_semantic=True, embedder=None) -> SearchOutcome`.
  - `query.search(...) -> list[QueryResult]` keeps its exact current signature and return type — every existing caller and test stays valid.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_searchdb_tokenize.py`:

```python
"""Query-side tokenizer.

Reviewer C F-C9: `tokenize()` was `re.findall(r"[a-z0-9]+", text.lower())` —
ASCII only — while the index is `unicode61` and DOES hold non-ASCII tokens
(the report's probe: MATCH "đường" → 1 hit). So `đường băng sân bay` became
['ng','b','ng','s','n','bay'] and `kb query` answered with two confident,
wrong results and no warning. C2 requires L2 in the source language, so a
Vietnamese KB would be indexed and unsearchable.
"""
import pytest

from center_kb import searchdb
from center_kb.hub import HubHandle
from center_kb.query import search_detailed
from tests.conftest import make_fed_entry


def test_tokenize_keeps_non_ascii_letters():
    assert searchdb.tokenize("đường băng sân bay") == [
        "đường", "băng", "sân", "bay",
    ]


def test_tokenize_treats_underscore_as_a_separator():
    """unicode61 does, so the query side must too — otherwise 'foo_bar'
    becomes a token the index can never contain."""
    assert searchdb.tokenize("foo_bar") == ["foo", "bar"]


def test_tokenize_still_splits_the_domain_punctuation():
    assert searchdb.tokenize("ARINC-424 §5.129 CUST/AREA") == [
        "arinc", "424", "5", "129", "cust", "area",
    ]


def test_vietnamese_term_round_trips_index_to_query(tmp_path, run_git):
    fed = tmp_path / "hub" / "federation"
    fed.mkdir(parents=True)
    (tmp_path / "hub" / ".kb").mkdir()
    make_fed_entry(
        fed, "vn-kb", "quy-chuan",
        sec_id="2.1", sec_title="Đường băng",
        l2="## 2.1 Đường băng\n\nĐường băng phải có ký hiệu nhận dạng rõ ràng.\n",
        l3="## 2.1 Đường băng\n\nĐường băng phải có ký hiệu nhận dạng rõ ràng.\n",
    )
    from center_kb.federation import write_federation_index

    write_federation_index(fed)
    hub = HubHandle(root=tmp_path / "hub")
    outcome = search_detailed(hub, "đường băng")
    assert outcome.results, "a Vietnamese query found nothing in a Vietnamese KB"
    assert outcome.results[0].section_id == "2.1"


def test_query_with_no_usable_tokens_says_so(fed_hub):
    outcome = search_detailed(HubHandle(root=fed_hub), "§§§ ---")
    assert outcome.results == []
    assert any("no searchable terms" in n for n in outcome.notes)


def test_empty_query_produces_no_note(fed_hub):
    """An empty query is the nav link's empty state, not a caller mistake."""
    outcome = search_detailed(HubHandle(root=fed_hub), "   ")
    assert outcome.notes == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb_tokenize.py -v`
Expected: FAIL — the tokenizer drops the Vietnamese letters; `search_detailed` does not exist.

- [ ] **Step 3: Make the tokenizer symmetric**

In `src/center_kb/searchdb.py`, replace `tokenize` (lines 533-538):

```python
def tokenize(text: str) -> list[str]:
    """Query-side tokens, symmetric with the index's `unicode61` tokenizer.

    Reviewer C F-C9: `[a-z0-9]+` dropped every non-ASCII letter while the FTS
    index holds them, so a Vietnamese query was shredded into 1-2 character
    fragments and answered confidently with junk. `[^\\W_]+` is unicode61's own
    rule: alphanumerics are token characters, and underscore is a separator."""
    return re.findall(r"[^\W_]+", text.lower(), re.UNICODE)
```

- [ ] **Step 4: Add the notes channel**

In `src/center_kb/query.py`, add the dataclass next to `QueryResult`:

```python
@dataclass
class SearchOutcome:
    """Results plus the out-of-band things the caller must be told.

    `notes` exists because an MCP agent never sees stderr: the truncation,
    ambiguity, unknown-tag and no-usable-terms signals have to travel with the
    payload (F-C5, F-C7, F-C9, F-C14)."""

    results: list["QueryResult"]
    notes: list[str] = field(default_factory=list)
```

(add `field` to the existing `from dataclasses import dataclass` import).

Rename the current `search` body to `search_detailed`, returning a `SearchOutcome`, and keep `search` as a wrapper. The whole existing body is unchanged except the return:

```python
def search_detailed(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    use_semantic: bool = True,
    embedder=None,  # center_kb.embed.Embedder | None — injectable for tests
) -> SearchOutcome:
    from center_kb import embed as embed_mod

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if semantic and embedder is None:
        logger.warning(
            "semantic search requested but no embedder is available — "
            'keyword results only (enable with: pip install "center-kb[embed]")'
        )
    notes: list[str] = []
    terms = tokenize(text)
    if text.strip() and not terms:
        notes.append(
            f"Note: '{text}' contains no searchable terms after tokenising — "
            "the index stores alphanumeric words, so punctuation-only queries "
            "match nothing.\n\n"
        )
        return SearchOutcome(results=[], notes=notes)
    fused, rows = _search_index(
        hub, embedder if use_semantic else None, text, tags
    )

    results: list[QueryResult] = []
    used = 0
    # ... the existing loop, unchanged ...
    return SearchOutcome(results=results, notes=notes)


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    use_semantic: bool = True,
    embedder=None,
) -> list[QueryResult]:
    """Backwards-compatible view of `search_detailed` — results only."""
    return search_detailed(
        hub, text, tags=tags, budget=budget, semantic=semantic,
        use_semantic=use_semantic, embedder=embedder,
    ).results
```

Delete the old `terms = tokenize(text)` line from inside the loop section (it now lives above).

- [ ] **Step 5: Render notes at both surfaces**

In `src/center_kb/cli.py`, the `query` command:

```python
    try:
        outcome = search_detailed(
            handle, text, tags=tag_list, budget=budget, semantic=semantic
        )
    except searchdb.IndexBusyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for note in outcome.notes:
        typer.secho(note.strip(), fg=typer.colors.YELLOW, err=True)
    results = outcome.results
```

(change the import at the top of the command to `from center_kb.query import search_detailed`.)

In `src/center_kb/mcp.py`, inside `kb_search`'s `_run()`:

```python
            outcome = search_detailed(hub, query, tags=tags, budget=budget)
            notes = "".join(outcome.notes)
            if not outcome.results:
                return notes + (
                    "No matching section found — try dropping tags or changing keywords."
                )
            note = _stale_note(hub) + notes + _ambiguity_note(outcome.results)
            return note + "\n\n".join(
                ... unchanged ...
                for r in outcome.results
            )
```

Change the module import at the top of `src/center_kb/mcp.py` to
`from center_kb.query import get_section, search_detailed`, and drop `search`
if nothing else in the file uses it.

Task 2's loop-starvation test monkeypatched `mcp_mod.search`; `kb_search` no
longer calls it. Update that test in the same commit so it keeps testing what
it was written to test:

```python
    def slow_search(*args, **kwargs):
        _time.sleep(0.5)
        from center_kb.query import SearchOutcome

        return SearchOutcome(results=[])

    monkeypatch.setattr(mcp_mod, "search_detailed", slow_search)
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_searchdb_tokenize.py tests/test_query.py tests/test_query_semantic.py tests/test_mcp.py tests/test_cli.py tests/test_web_ui.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/searchdb.py src/center_kb/query.py src/center_kb/cli.py src/center_kb/mcp.py tests/test_searchdb_tokenize.py tests/test_mcp.py
git commit -m "fix(search): unicode-symmetric tokenizer and a notes channel (F-C9)"
```

---

### Task 9: Say when the leg cap truncated the results (F-C7)

**Files:**
- Create: `tests/test_query_truncation.py`
- Modify: `src/center_kb/query.py` (`_search_index`, `search_detailed`)

**Interfaces:**
- Consumes: `query.SearchOutcome` and `query.search_detailed` from Task 8.
- Produces: `_search_index` returns `(fused, rows, truncated: bool)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_truncation.py`:

```python
"""Leg-cap truncation.

Reviewer C F-C7: `K_LEG = 50` caps each leg before RRF and nothing told the
caller. `record` matched 154 sections in FTS and returned 50; `runway` matched
63 and returned 50 — under a docstring that tells agents kb_search "Returns
every relevant section found". For a broad BA query that is a false assurance.
"""
import pytest

pytest.importorskip("sqlite_vec")

from center_kb import searchdb  # noqa: E402
from center_kb.federation import write_federation_index  # noqa: E402
from center_kb.hub import HubHandle  # noqa: E402
from center_kb.query import search_detailed  # noqa: E402
from tests.conftest import make_fed_entry  # noqa: E402


def _wide_hub(tmp_path, n_sections: int) -> HubHandle:
    """One doc whose N sections all contain the term 'record'."""
    from center_kb import models
    from center_kb.federation import FederationMeta

    fed = tmp_path / "hub" / "federation"
    entry = fed / "wide-kb" / "wide-doc"
    entry.mkdir(parents=True)
    (tmp_path / "hub" / ".kb").mkdir(parents=True)
    body = "".join(
        f"## {i}.0 Record {i}\n\nThis section describes record {i} in detail.\n\n"
        for i in range(1, n_sections + 1)
    )
    (entry / "ch1.md").write_text(body, encoding="utf-8")
    (entry / "ch1.raw.md").write_text(body, encoding="utf-8")
    models.save_yaml_model(
        entry / "_manifest.yaml",
        models.Manifest(
            id="wide-doc", title="Wide Doc",
            sections=[
                models.SectionEntry(
                    id=f"{i}.0", title=f"Record {i}",
                    summary=f"Record {i}.", status="summarized", file="ch1",
                )
                for i in range(1, n_sections + 1)
            ],
        ),
    )
    models.save_yaml_model(
        fed / "wide-kb" / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id="wide-doc", title="Wide Doc", tags=["wide"], summary="Wide."
        )]),
    )
    models.save_yaml_model(
        fed / "wide-kb" / "_meta.yaml",
        FederationMeta(
            repo_id="wide-kb", source_commit="abc1234",
            published_at="2026-07-13T00:00:00+00:00",
        ),
    )
    write_federation_index(fed)
    return HubHandle(root=tmp_path / "hub")


def test_note_when_the_leg_cap_truncated(tmp_path):
    hub = _wide_hub(tmp_path, searchdb.K_LEG + 20)
    outcome = search_detailed(hub, "record", budget=10_000_000)
    assert any("more sections matched" in n for n in outcome.notes)


def test_no_note_when_everything_fit(tmp_path):
    hub = _wide_hub(tmp_path, searchdb.K_LEG - 10)
    outcome = search_detailed(hub, "record", budget=10_000_000)
    assert not any("more sections matched" in n for n in outcome.notes)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_query_truncation.py -v`
Expected: FAIL on `test_note_when_the_leg_cap_truncated` — no such note.

- [ ] **Step 3: Report truncation from `_search_index`**

In `src/center_kb/query.py`, change `_search_index` to also report whether a leg filled its cap. No `searchdb` signature changes are needed — a leg that returned exactly `K_LEG` rows is a leg that was cut:

```python
def _search_index(
    hub: "HubHandle", embedder, text: str, tags: list[str] | None
) -> tuple[list[tuple[int, float, str]], dict[int, "SectionRow"], bool]:
    """Run both legs + RRF on the index. DB corrupt mid-way → delete, rebuild
    exactly once; still failing → raise (spec §5). The third element is True
    when a leg filled K_LEG, i.e. matches were dropped before fusion (F-C7)."""
```

and in the success path:

```python
            fused = searchdb.rrf_merge(fts_hits, knn_hits)
            truncated = (
                len(fts_hits) >= searchdb.K_LEG or len(knn_hits) >= searchdb.K_LEG
            )
            return (
                fused,
                searchdb.load_sections(conn, [r for r, _, _ in fused]),
                truncated,
            )
```

- [ ] **Step 4: Turn it into a note**

In `search_detailed`:

```python
    fused, rows, truncated = _search_index(
        hub, embedder if use_semantic else None, text, tags
    )
```

and after the result loop, before `return`:

```python
    if truncated:
        # Deliberately conservative: a query with exactly K_LEG matches reports a
        # cut it did not suffer. That costs the caller one sentence and never
        # hides a real one (F-C7).
        notes.append(
            f"Note: more sections matched than were ranked — each leg is capped "
            f"at {searchdb.K_LEG} before fusion, so this is not the complete set. "
            "Narrow the query or add --tags to see the rest.\n\n"
        )
```

Add `from center_kb import searchdb` at the top of `search_detailed` (the module already imports `searchdb` lazily inside `_search_index`; a local import in `search_detailed` keeps that pattern).

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_query_truncation.py tests/test_query.py tests/test_mcp.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/query.py tests/test_query_truncation.py
git commit -m "feat(query): warn when the leg cap dropped matches (F-C7)"
```

---

### Task 10: An ambiguity note that actually fires (F-C5)

**Files:**
- Create: `tests/test_query_ambiguity.py`
- Modify: `src/center_kb/query.py` (`_search_index`, `search_detailed`)
- Modify: `src/center_kb/mcp.py:25-44` (`_ambiguity_note` keeps its hybrid rule; the new note arrives via `outcome.notes`)

**Interfaces:**
- Consumes: `query.SearchOutcome` (Task 8), `_search_index`'s 3-tuple (Task 9).
- Produces: `_search_index` returns a 4-tuple, adding `fts_scores: dict[int, float]` (rowid → positive BM25 score, higher is better).

- [ ] **Step 1: Write the failing test**

Create `tests/test_query_ambiguity.py`:

```python
"""The close-top-2 note.

Reviewer C F-C5: README §7.8 promises kb_search "flags when the top two are
close in score". `_ambiguity_note` requires BOTH hits to be `hybrid`, which
cannot happen without an embedder — so on the shipped default it fired 0/14
times, including on "Restrictive Airspace Designation" where
`beta:arinc-424 §5.129` and `aero:arinc-424 §5.129` were ranks 1 and 2: exactly
the case a BA must be warned about. With the semantic floor lowered so both
legs contribute it fired 9/10, including on unambiguous queries. The flag has
no calibrated middle.

RRF carries no magnitude — adjacent ranks in one leg are always ~1.6% apart —
so the score half of the rule has to read raw BM25.
"""
import pytest

pytest.importorskip("sqlite_vec")

from center_kb.federation import write_federation_index  # noqa: E402
from center_kb.hub import HubHandle  # noqa: E402
from center_kb.query import search_detailed  # noqa: E402
from tests.conftest import make_fed_entry  # noqa: E402


@pytest.fixture
def colliding_hub(fed_hub):
    """A second repo publishing the same doc id AND the same section id."""
    make_fed_entry(
        fed_hub / "federation", "beta-kb", "arinc-424",
        tags=["arinc424"],
        sec_id="5.3", sec_title="Restrictive Airspace",
        sec_summary="Restrictive airspace: designation, type, multiple code.",
        l2="## 5.3 Restrictive Airspace\n\nCondensed: restrictive airspace designation codes.\n",
        l3="## 5.3 Restrictive Airspace\n\nFull raw restrictive airspace text.\n",
    )
    write_federation_index(fed_hub / "federation")
    return HubHandle(root=fed_hub)


def test_federation_collision_always_flags(colliding_hub):
    outcome = search_detailed(colliding_hub, "restrictive airspace designation")
    assert len(outcome.results) >= 2
    note = "".join(outcome.notes)
    assert "same section" in note
    assert "arinc-kb:arinc-424 §5.3" in note
    assert "beta-kb:arinc-424 §5.3" in note


def test_unambiguous_query_is_silent(fed_hub):
    outcome = search_detailed(HubHandle(root=fed_hub), "restrictive airspace designation")
    assert not any("same section" in n or "score closely" in n for n in outcome.notes)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_query_ambiguity.py -v`
Expected: FAIL on `test_federation_collision_always_flags` — no such note.

- [ ] **Step 3: Carry the keyword leg's raw scores out of the index**

In `src/center_kb/query.py`, `_search_index` returns a 4-tuple:

```python
) -> tuple[
    list[tuple[int, float, str]], dict[int, "SectionRow"], bool, dict[int, float]
]:
```

and in the success path:

```python
            return (
                fused,
                searchdb.load_sections(conn, [r for r, _, _ in fused]),
                truncated,
                dict(fts_hits),
            )
```

- [ ] **Step 4: Compute the note**

In `src/center_kb/query.py`, add above `search_detailed`:

```python
# Chosen by measurement in Task 10, Step 6 — see that step before changing it.
AMBIG_BM25_RATIO = 0.95


def _ambiguity_notes(
    results: list["QueryResult"],
    fused: list[tuple[int, float, str]],
    fts_scores: dict[int, float],
) -> list[str]:
    """Two reasons the caller should look at #2 as well as #1 (F-C5).

    1. STRUCTURAL — the top two are the SAME section published by two
       federation repos. No threshold, no calibration, and it is the case a BA
       must never miss.
    2. SCORE — both come from the keyword leg and their raw BM25 scores are
       within AMBIG_BM25_RATIO. RRF cannot answer this: adjacent ranks within a
       leg are always ~1.6% apart, so a ratio test on RRF fires on everything
       or nothing. BM25 carries real magnitude."""
    if len(results) < 2:
        return []
    top, second = results[0], results[1]
    if top.doc_id == second.doc_id and top.section_id == second.section_id:
        return [
            f"Note: [{top.citation}] and [{second.citation}] are the same section "
            "published by two federation repos — confirm which repo the story "
            "should cite before pinning.\n\n"
        ]
    ranked = [rowid for rowid, _, _ in fused][:2]
    if len(ranked) == 2 and all(r in fts_scores for r in ranked):
        if top.match_mode == "keyword" and second.match_mode == "keyword":
            hi, lo = fts_scores[ranked[0]], fts_scores[ranked[1]]
            if hi > 0 and lo / hi >= AMBIG_BM25_RATIO:
                return [
                    f"Note: [{top.citation}] and [{second.citation}] score closely "
                    "— both may be relevant to your question; review each before "
                    "citing.\n\n"
                ]
    return []
```

Update `search_detailed`'s unpack to the 4-tuple and call the new function after the truncation note:

```python
    fused, rows, truncated, fts_scores = _search_index(
        hub, embedder if use_semantic else None, text, tags
    )
```

```python
    notes.extend(_ambiguity_notes(results, fused, fts_scores))
```

`mcp.py`'s `_ambiguity_note` (the hybrid/tie rule) stays exactly as it is — it is still the right rule when both legs are live, and leaving it untouched keeps the four committed goldens stable.

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_query_ambiguity.py tests/test_query.py tests/test_mcp.py -v`
Expected: PASS.

- [ ] **Step 6: Measure `AMBIG_BM25_RATIO` on the real corpus, then keep or change it**

The spec forbids shipping another unmeasured constant (that is F-C11's complaint about `SEMANTIC_MIN_SCORE`). Publish the repo's own `.kb/` to a scratch hub and print the top-2 BM25 ratio for reviewer C's battery:

```bash
.venv/Scripts/python -c "
import shutil, subprocess, tempfile
from pathlib import Path
from center_kb import searchdb
from center_kb.hub import HubHandle
from center_kb.query import _search_index

QUERIES = [
    'Restrictive Airspace Designation', 'Runway Identifier', 'Magnetic Variation',
    'CUST/AREA', 'S/T', 'ARPT/HELI IDENT', 'RT TYPE', 'IFR CAP', '5.129',
    'section 5.4', 'Continuation Record Number', 'Section Code',
    'which field says whether a record is standard or tailored',
    'how do I know if an airport supports IFR',
]
tmp = Path(tempfile.mkdtemp())
fed = tmp / 'federation' / 'aero'
fed.parent.mkdir(parents=True)
shutil.copytree('.kb', fed)
(tmp / '.kb').mkdir()
from center_kb.federation import FederationMeta, write_federation_index
from center_kb import models
models.save_yaml_model(fed / '_meta.yaml', FederationMeta(
    repo_id='aero', source_commit='0000000',
    published_at='2026-09-10T00:00:00+00:00'))
write_federation_index(tmp / 'federation')
hub = HubHandle(root=tmp)
for q in QUERIES:
    fused, rows, _, fts = _search_index(hub, None, q, None)
    ids = [r for r, _, _ in fused][:2]
    if len(ids) == 2 and all(i in fts for i in ids):
        hi, lo = fts[ids[0]], fts[ids[1]]
        print(f'{lo/hi:.3f}  {q}')
print(tmp)
"
```

Every query in that list is one reviewer C scored ✔ rank-1, so **none of them should fire**. Set `AMBIG_BM25_RATIO` just above the highest ratio printed (round up to two decimals). If the highest is ≥ 0.99 — i.e. no value separates the unambiguous queries from a genuinely close pair — stop and report it instead of guessing; the structural rule still stands on its own. Record the printed table in the commit message.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/query.py tests/test_query_ambiguity.py
git commit -m "fix(query): make the close-top-2 note fire on the keyword-only path (F-C5)"
```

---

### Task 11: Hint the published tags when a filter matches nothing (F-C14)

**Files:**
- Modify: `src/center_kb/query.py` (`search_detailed`)
- Test: `tests/test_query.py`

**Interfaces:**
- Consumes: `query.SearchOutcome` (Task 8), `kbcontext.tag_vocabulary(repos) -> dict[str, str]`.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_query.py`:

```python
def test_unknown_tag_lists_the_published_vocabulary(fed_hub):
    """Reviewer C battery #32: `--tags nonexistent-tag` returned 0 results with
    no hint that the tag itself was the problem."""
    from center_kb.query import search_detailed

    outcome = search_detailed(_handle(fed_hub), "runway", tags=["nonexistent-tag"])
    assert outcome.results == []
    note = "".join(outcome.notes)
    assert "nonexistent-tag" in note
    assert "arinc424" in note  # a real published tag


def test_doc_id_is_an_accepted_tag(fed_hub):
    """F-C14: searchdb.py:350 indexes doc.id.lower() as a synthetic tag, so
    `--tags arinc-424` works. It stays supported and must not be reported as
    unknown; it deliberately does NOT join the kb-context tag vocabulary."""
    from center_kb.query import search_detailed

    outcome = search_detailed(_handle(fed_hub), "restrictive", tags=["arinc-424"])
    assert outcome.results
    assert outcome.notes == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_query.py -k tag -v`
Expected: FAIL — no note.

- [ ] **Step 3: Add the hint**

In `src/center_kb/query.py`, at the end of `search_detailed`, only when a tag filter produced nothing (so the extra federation load never touches the hot path):

```python
    if not results and tags:
        notes.extend(_unknown_tag_notes(hub, tags))
```

and add above `search_detailed`:

```python
def _unknown_tag_notes(hub: "HubHandle", tags: list[str]) -> list[str]:
    """A tag filter that matched nothing is usually a tag that does not exist
    (reviewer C battery #32). Only runs on the empty-result path.

    Document ids count as valid: `searchdb.py:350` indexes `doc.id.lower()` as
    a synthetic tag, so `--tags arinc-424` is a supported filter (F-C14). It is
    deliberately NOT part of `kbcontext.tag_vocabulary`, which governs what a
    kb-context block may carry."""
    from center_kb import kbcontext
    from center_kb.federation import load_federation

    repos = load_federation(hub.federation_dir)
    vocab = kbcontext.tag_vocabulary(repos)
    doc_ids = {doc.id.lower() for repo in repos for doc in repo.index.docs}
    known = set(vocab) | doc_ids
    unknown = sorted({t.strip().lower() for t in tags if t.strip()} - known)
    if not unknown:
        return []
    published = ", ".join(sorted(vocab.values())) or "(none published)"
    return [
        f"Note: no document is tagged {', '.join(repr(t) for t in unknown)}. "
        f"Published tags: {published}. Document ids are also accepted as tags."
        "\n\n"
    ]
```

- [ ] **Step 4: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_query.py tests/test_mcp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/query.py tests/test_query.py
git commit -m "feat(query): name the published tags when a tag filter matches nothing (F-C14)"
```

---

### Task 12: "The cited thing no longer exists" is `broken` (F-C6)

**Files:**
- Modify: `src/center_kb/resolve.py:37-53` (`_worktree_section`), `:95-113` (`_resolve_one` tail), `:113-152` (`resolve_refs`)
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `kbcontext.KBContext.hub_version` (already parsed at `kbcontext.py:190-191`).
- Produces: `_worktree_section` returns `tuple[str | None, str]` — `(content, problem)` where problem is `""`, `"missing-doc"`, `"missing-section"` or `"bad-manifest"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolve.py`. The file already has `_ctx_for(fed_hub, refs)`, which pins a real block at hub HEAD; `resolve_refs` reads "now" from the hub worktree at `federation/<repo>/<doc>/`, so the mutations below need no commit. These are cases (e), (f), (g) and (a) of reviewer C's battery:

```python
import shutil

import yaml

REF = "arinc-kb:arinc-424 §5.3"


def _doc_dir(fed_hub):
    return fed_hub / "federation" / "arinc-kb" / "arinc-424"


def test_deleted_section_is_broken(fed_hub):
    """(e) — the section is removed from the manifest.

    Reviewer C F-C6: this resolved as `stale`/exit 2, the same signal CI gets
    for "someone reworded a sentence", so CI could not block on a citation
    whose target is gone. C8's three statuses stay three — this is a
    reclassification, not a new status."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    manifest = _doc_dir(fed_hub) / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["sections"] = [s for s in data["sections"] if s["id"] != "5.3"]
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "no longer exists" in result.reason
    assert result.content, "the pinned bytes still resolve — only the link is broken"


def test_renumbered_section_is_broken(fed_hub):
    """(f) — §5.3 becomes §5.3a."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    manifest = _doc_dir(fed_hub) / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    for sec in data["sections"]:
        if sec["id"] == "5.3":
            sec["id"] = "5.3a"
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "no longer exists" in result.reason


def test_removed_document_is_broken_and_hints_a_command_that_works(fed_hub):
    """(g) — the whole document is gone. The old `stale` hint was a dead end:
    `kb diff arinc-424 --against <rev>` answers `doc 'arinc-424' is not in the
    worktree`."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    shutil.rmtree(_doc_dir(fed_hub))

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "document" in result.reason and "no longer exists" in result.reason
    assert "kb diff" not in render_resolved([result])


def test_l2_edit_is_still_stale(fed_hub):
    """(a) — a genuine amendment must NOT be promoted to broken."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    l2 = _doc_dir(fed_hub) / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("Condensed:", "Condensed (rev 2):"),
        encoding="utf-8",
    )
    (result,) = resolve_refs(handle, ctx)
    assert result.status == "stale"
    assert "kb diff" in render_resolved([result])


def test_legacy_two_version_block_is_broken(fed_hub):
    """F-C6 nit: `hub_version` was parsed at kbcontext.py:190-191 and never
    consulted, so a legacy two-version block whose `version` happened to be a
    real hub commit resolved silently as ok."""
    handle = HubHandle(root=fed_hub)
    pinned = _ctx_for(fed_hub, [REF])
    ctx = KBContext(
        version=pinned.version, hub_version="deadbee", refs=pinned.refs
    )
    results = resolve_refs(handle, ctx)
    assert all(r.status == "broken" for r in results)
    assert "hub_version" in results[0].reason
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_resolve.py -v`
Expected: FAIL — the three removal cases return `stale`, and the legacy block resolves `ok`.

- [ ] **Step 3: Make `_worktree_section` say *why* it failed**

In `src/center_kb/resolve.py`:

```python
MISSING_DOC = "missing-doc"
MISSING_SECTION = "missing-section"
BAD_MANIFEST = "bad-manifest"


def _worktree_section(kb_dir: Path, ref: KBRef) -> tuple[str | None, str]:
    """(content, problem). `problem` is '' when the content was read.

    Reviewer C F-C6: this used to return None for all three failures, so
    `_resolve_one` collapsed "the cited standard section no longer exists" into
    the same `stale` bucket as "someone reworded a sentence"."""
    manifest_path = kb_dir / ref.doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None, MISSING_DOC
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, ValidationError):
        return None, BAD_MANIFEST
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return None, MISSING_SECTION
    l2 = kb_dir / ref.doc_id / f"{sec.file}.md"
    if not l2.exists():
        return None, MISSING_SECTION
    return slice_section(l2.read_text(encoding="utf-8"), ref.section_id), ""
```

- [ ] **Step 4: Reclassify in `_resolve_one`**

Replace the status block at the end of `_resolve_one` (lines 95-113):

```python
    citation = f"{ref} ({manifest.revision})" if manifest.revision else str(ref)
    now, problem = _worktree_section(kb_dir, ref)
    reasons = {
        MISSING_DOC: (
            f"the cited document '{ref.doc_id}' no longer exists in the "
            "federation — confirm the replacement with the BA, then re-pin "
            "with kb_context_new"
        ),
        MISSING_SECTION: (
            f"the cited section §{ref.section_id} no longer exists in "
            f"'{ref.doc_id}' at the current revision (deleted or renumbered) — "
            "confirm the replacement with the BA, then re-pin with kb_context_new"
        ),
        BAD_MANIFEST: (
            f"manifest for '{ref.doc_id}' is unreadable in the worktree"
        ),
    }
    if problem:
        # broken, not stale: CI must be able to BLOCK on a citation whose target
        # is gone, and must not treat it like an amendment (F-C6). The pinned
        # bytes still resolve, so they travel with the failure.
        return ResolvedRef(
            ref=ref, status="broken", citation=citation, content=pinned,
            tokens=count_tokens(pinned), reason=reasons[problem], pinned_rev=rev,
        )
    if now.strip() != pinned.strip():
        status: Status = "stale"
        reason = "L2 content has changed since the pinned version (amendment after the BA wrote it)"
    else:
        status = "ok"
        reason = ""
```

`render_resolved` needs no change: the `kb diff` hint lives only in its `stale` branch, so the dead-end hint disappears with the reclassification.

- [ ] **Step 5: Consult `hub_version`**

In `src/center_kb/resolve.py`, in `resolve_refs`, immediately after the `rev_exists` guard:

```python
    if ctx.hub_version and ctx.hub_version != ctx.version:
        # F-C6 nit: `hub_version` was parsed and never read, so a legacy
        # two-version block whose `version` happened to be a real hub commit
        # resolved silently as ok — pinning something nobody chose.
        reason = (
            f"kb-context carries both version {ctx.version} and hub_version "
            f"{ctx.hub_version} — a legacy two-version block; re-pin with "
            "kb_context_new"
        )
        return [_broken(ref, reason, pinned_rev=ctx.version) for ref in ctx.refs]
```

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_resolve.py tests/test_kbcontext.py tests/test_cli_context.py tests/test_cli_doctor_diff.py tests/test_mcp.py -v`
Expected: PASS. `kb resolve` and `kb doctor --context` map broken → exit 1 already; confirm no test asserted exit 2 for a removal case.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/resolve.py tests/test_resolve.py
git commit -m "fix(resolve): a removed section or document is broken, not stale (F-C6)"
```

---

### Task 13: Hub hygiene — `.kb-work/` must not be committed (F-C17)

**Files:**
- Create: `src/center_kb/templates/init/hub-gitignore.txt`
- Modify: `src/center_kb/initcmd.py:46-54` (`HUB_TEMPLATES`)
- Modify: `src/center_kb/doctor.py` (`check_hub`)
- Test: `tests/test_init.py`, `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `kb init --kind hub` writes `.gitignore`; `check_hub` emits one new warning.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
def test_hub_scaffold_ignores_the_search_index(tmp_path):
    """Reviewer C F-C17: the index lives at <hub>/.kb-work/search.db and shows
    up as untracked `?? .kb-work/`. No init scaffold covered it, so a hub
    maintainer running `git add -A` commits a multi-MB binary."""
    from center_kb import initcmd

    initcmd.init_repo(tmp_path, "hub")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".kb-work/" in text
```

Append to `tests/test_doctor_hub.py`:

```python
def test_doctor_warns_when_the_index_is_untracked_and_unignored(fed_hub):
    from center_kb import doctor
    from center_kb.hub import HubHandle

    work = fed_hub / ".kb-work"
    work.mkdir(exist_ok=True)
    (work / "search.db").write_bytes(b"\x00")

    issues, _ = doctor.check_hub(fed_hub / ".kb", HubHandle(root=fed_hub))
    assert any(".kb-work/" in i.message for i in issues)

    (fed_hub / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    issues, _ = doctor.check_hub(fed_hub / ".kb", HubHandle(root=fed_hub))
    assert not any(".kb-work/" in i.message for i in issues)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_doctor_hub.py -k "gitignore or kb_work or index" -v`
Expected: FAIL — no `.gitignore` in the hub scaffold, no doctor warning.

- [ ] **Step 3: Add the template**

Create `src/center_kb/templates/init/hub-gitignore.txt`:

```
# The hybrid search index — rebuilt on demand from federation/, never reviewed.
# Without this line `git add -A` on the hub commits a multi-MB binary.
.kb-work/
```

Register it in `src/center_kb/initcmd.py`:

```python
HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    ".gitignore": "hub-gitignore.txt",
    "docker-compose.yml": "docker-compose-hub.yml",
    ...
}
```

- [ ] **Step 4: Warn on existing hubs**

In `src/center_kb/doctor.py`, inside `check_hub`, after the stale-cache block:

```python
    work = handle.root / ".kb-work"
    if work.is_dir():
        ignore = handle.root / ".gitignore"
        ignored = (
            ignore.exists()
            and ".kb-work" in ignore.read_text(encoding="utf-8")
        )
        if not ignored:
            issues.append(
                Issue(
                    "warning",
                    "the search index at .kb-work/ is neither ignored nor "
                    "meant to be committed — add '.kb-work/' to the hub's "
                    ".gitignore before someone runs `git add -A` (F-C17)",
                )
            )
```

- [ ] **Step 5: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_init.py tests/test_templates.py tests/test_doctor_hub.py tests/test_doctor.py tests/test_check_package.py -v`
Expected: PASS. `test_check_package.py` verifies the wheel ships the templates directory — the new file must be picked up by the existing glob.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/hub-gitignore.txt src/center_kb/initcmd.py src/center_kb/doctor.py tests/test_init.py tests/test_doctor_hub.py
git commit -m "fix(init,doctor): keep the search index out of the hub's git history (F-C17)"
```

---

### Task 14: Gate tests fail instead of hanging, and stop being POSIX-shaped (F-C1, F-C17)

**Files:**
- Modify: `tests-gate/regression/test_golden_output.py:50-56` (`NOISE`), `:100-146` (the four `asyncio.run` calls)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Add a hard timeout to every golden MCP call**

Reviewer C could not run these four cases at all: they hang (F-C1) with no teardown, so the gate stalls instead of going red. In `tests-gate/regression/test_golden_output.py`, wrap the call helper:

```python
GOLDEN_TIMEOUT_S = 60


async def _call_mcp(params, tool: str, args: dict) -> str:
    """params: StdioServerParameters — prebuilt by the published_kb_mcp_params
    fixture (tests-gate/conftest.py, Task 9) via the shared _mcp_stdio_params
    helper. Do not rebuild StdioServerParameters here.

    The hard timeout is not decoration: reviewer C's F-C1 made kb_search hang
    forever over stdio, and this file hung with it — a gate that hangs is worse
    than a gate that fails, because nobody sees red."""
    import anyio
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    with anyio.fail_after(GOLDEN_TIMEOUT_S):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, args)
                return "".join(c.text for c in result.content if c.type == "text")
```

- [ ] **Step 2: Mask Windows temp paths**

`NOISE` masks only `/tmp/...`, so the goldens are POSIX-shaped by construction (F-C17). Add the Windows form:

```python
NOISE = [
    (re.compile(r"/tmp/[^\s\"']+"), "<TMP>"),
    # Windows temp: C:\Users\...\AppData\Local\Temp\... — without this the
    # goldens can only ever be generated on POSIX (F-C17).
    (re.compile(r"[A-Za-z]:\\\\[^\s\"']*?\\\\Temp\\\\[^\s\"']+"), "<TMP>"),
    (re.compile(r"[A-Za-z]:\\[^\s\"']*?\\Temp\\[^\s\"']+"), "<TMP>"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "<SHA>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T[\d:.+]+"), "<TS>"),
]
```

- [ ] **Step 3: Run the gate regression tier**

Run: `KB_VENV=$PWD/.venv .venv/Scripts/python -m pytest tests-gate/regression -v`
Expected: PASS for `test_mcp_contract.py` and all four golden cases. If a golden differs, **stop** — a golden change is Task 16's business and must be deliberate.

- [ ] **Step 4: Commit**

```bash
git add tests-gate/regression/test_golden_output.py
git commit -m "test(gate): hard timeout on golden MCP calls; mask Windows temp paths"
```

---

### Task 15: Docs and docstrings tell the truth (F-C13, F-C7, F-C8, F-C14)

**Files:**
- Modify: `README.md` §7.5 (lines 376-406) and §7.8 (lines 435-472)
- Modify: `src/center_kb/mcp.py` (`kb_search` docstring)
- Modify: `tests-gate/golden/mcp_tools.json` (regenerated)
- Test: `tests/test_readme.py`

**Interfaces:**
- Consumes: everything above.
- Produces: nothing.

- [ ] **Step 1: Write the failing README pins**

Append to `tests/test_readme.py`:

```python
def test_readme_shows_the_real_query_output():
    """Reviewer C F-C13: §7.5 still showed `score=17.19` and an unqualified
    `[arinc-424 §5.129 ...]`. `_citation` (query.py:47-49) prefixes `repo_id:`
    unconditionally — there is no 'only on ambiguity' branch — and `score=` was
    removed in the hybrid rework."""
    text = _normalised(_readme_text())
    assert "match=keyword" in text
    assert "score=17.19" not in text
    assert "citation of the form `<repo-id>:<doc-id> §<section> (<revision>)`" in text


def test_readme_does_not_promise_every_relevant_section():
    """F-C7: each leg is capped at K_LEG=50 before RRF."""
    text = _normalised(_readme_text())
    assert "returns every relevant section found" not in text
    assert "each leg is capped at 50 results before fusion" in text


def test_readme_documents_the_advisory_budget():
    """F-C8: `query.py:173` always admits result #1, whatever its size — a
    caller asking for 50 tokens can receive a 1488-token section."""
    text = _normalised(_readme_text())
    assert "the first result is always returned whatever its size" in text


def test_readme_documents_doc_ids_as_tags():
    """F-C14: searchdb.py:350 indexes doc.id.lower() as a synthetic tag."""
    text = _normalised(_readme_text())
    assert "a document id is also accepted as a tag" in text
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_readme.py -v`
Expected: FAIL on all four.

- [ ] **Step 3: Fix README §7.5**

In the fenced sample, replace the two result headers and the citation paragraph:

```
--- [aero:arinc-424 §5.129 (Supplement 22)] match=keyword ~246tk
```

```
--- [aero:arinc-424 §5.126 (Supplement 22)] match=keyword ~103tk
```

and replace the "Results always include…" paragraph with:

> Results always include a **clear citation** of the form `<repo-id>:<doc-id> §<section> (<revision>)` — e.g. `aero:arinc-424 §5.129 (Supplement 22)` — so you know exactly which federation repo, document and revision the info came from. The repo id is always present, not only when a document id is ambiguous.

Add to the parameter table's `--budget` row, or as a sentence below it:

> `--budget` is advisory: the first result is always returned whatever its size, so a very large section can exceed a small budget. Sections are never cut in the middle, which is what keeps tables verbatim.

Add to the `--tags` row, or the same paragraph:

> a document id is also accepted as a tag (`--tags arinc-424`), alongside the content tags a document publishes.

- [ ] **Step 4: Fix README §7.8 and the docstring together**

In the `kb_search` row of the tools table, replace the promise:

> `kb_search` | Find sections by natural language (tag match + hybrid FTS5/semantic search), return L2 within a token budget. Ranking is capped: each leg is capped at 50 results before fusion, and the tool says so when matches were dropped. It also flags when the top two results are the same section published by two federation repos, or score closely on the keyword leg | `query`, `tags`, `budget`

Fix the stale count in the closing note of §7.8 — it says "the four tools" while §7.8's own table lists five:

> **Note:** `.mcp.json` already configures the MCP server in-repo — no extra setup for Claude Code to see the five tools.

Then bring `kb_search`'s docstring in `src/center_kb/mcp.py` in line — this is the **only** task allowed to change a docstring:

```python
        """Find sections by hybrid search (FTS5 keyword + semantic KNN, RRF-fused);
        return L2 content within the token budget, with citations. Returns the
        top-ranked sections, not just the best match — each leg is capped at 50
        results before fusion, and a note says so when matches were dropped.
        When using this to draft a User Story, show ALL returned sections (with
        their citations) to the user and confirm which ones actually apply
        before writing story content from them. Citing more than one section
        for a single story is normal. Once confirmed, call kb_context_new with
        the confirmed refs to pin them for the ticket. Results come from the
        hub federation — unpublished local content never appears."""
```

- [ ] **Step 5: Regenerate the golden tool snapshot, deliberately**

Run: `KB_VENV=$PWD/.venv UPDATE_GOLDEN=1 .venv/Scripts/python -m pytest tests-gate/regression -v`

Then `git diff tests-gate/golden/` and confirm by eye that the **only** change is `kb_search`'s `description` text. Any other diff — a parameter, a type, another tool — means an earlier task broke the wire contract: stop and fix that instead.

- [ ] **Step 6: Run the tests**

Run: `.venv/Scripts/python -m pytest tests/test_readme.py -v` and `KB_VENV=$PWD/.venv .venv/Scripts/python -m pytest tests-gate/regression -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md src/center_kb/mcp.py tests-gate/golden/ tests/test_readme.py
git commit -m "docs: README §7.5/§7.8 and kb_search docstring match the code (F-C13, F-C7, F-C8, F-C14)"
```

---

### Task 16: Full-suite verification

**Files:** none — verification only.

- [ ] **Step 1: Run the whole unit suite**

Run: `.venv/Scripts/python -m pytest tests -q`
Expected: PASS. Budget 10–19 minutes; this is the only time the full suite runs in this batch.

- [ ] **Step 2: Run the release gate**

Run: `./scripts/gate.sh`
Expected: PASS. If `gate.sh` cannot run on this machine, run `KB_VENV=$PWD/.venv .venv/Scripts/python -m pytest tests-gate -q` and say so in the report.

- [ ] **Step 3: Lint**

Run: `.venv/Scripts/python -m ruff check src tests tests-gate`
Expected: clean.

- [ ] **Step 4: Walk the acceptance list from the spec**

Confirm each of these by pointing at the test that proves it, and report anything that does not hold:

| Acceptance (spec) | Proof |
|---|---|
| `kb_search` answers over real stdio | `tests/test_mcp_stdio.py` |
| golden schema + four golden outputs pass on the wheel | `tests-gate/regression` |
| five concurrent cold builds exit 0, no traceback | `tests/test_searchdb_concurrency.py` |
| 40 000 tags: clean refusal, `search.db` survives | `tests/test_searchdb.py` |
| hub-side commit visible to the next query; `kb get` agrees | `tests/test_query_freshness.py` |
| `kb get --level L3` exits 1; `--level l3` returns verbatim | `tests/test_query_level.py` |
| resolve cases e/f/g exit 1; a exits 2; b/c exit 0 | `tests/test_resolve.py` |
| a Vietnamese query retrieves a Vietnamese section | `tests/test_searchdb_tokenize.py` |
| `kb init --kind hub` leaves `git status` clean after a query | `tests/test_init.py`, `tests/test_doctor_hub.py` |
| README §7.5/§7.8 match the shipped output | `tests/test_readme.py` |

- [ ] **Step 5: Commit any fixes, then open the PR**

```bash
git push -u origin feat/c-search-mcp-fixes
gh pr create --title "fix: reviewer C batch — reachable MCP surface, honest index, no silent substitutions" --body-file <(cat <<'EOF'
Implements `docs/superpowers/specs/2026-09-10-search-mcp-context-review-fixes-design.md`.

Findings closed: F-C1, F-C2, F-C3, F-C4, F-C5, F-C6, F-C7, F-C9, F-C10, F-C13, F-C14, F-C17.
F-C8 is documented, not changed. F-C11, F-C12, F-C15 and F-C16 are out of scope — see the spec.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)
```
