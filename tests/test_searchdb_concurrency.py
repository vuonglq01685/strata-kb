"""Cold-build concurrency.

Reviewer C F-C2: five `kb query` processes against a hub with no search.db —
the normal state after a fresh clone, or several agents starting at once —
gave 3/5 failures on EVERY trial, each with a raw rich traceback:

    search.db corrupt — rebuilding once: UNIQUE constraint failed: ...
    PermissionError: [WinError 32] The process cannot access the file ...

`searchdb.py:322-336` claims "losing the race must be idempotent and must not
break UNIQUE"; this test is that claim.

Review fix (round 2, Finding 3): `kb query` exits 0 when it finds nothing
(cli.py) and the F-C2 "client" branch now prints its clean message to
**stdout** (cli.py's `typer.secho`, no `err=True`), not stderr — so the
original stderr-only assertions could pass vacuously (five broken processes
that all found nothing) or silently lose their teeth (a caught lost race no
longer appears in stderr at all). The assertions below check
`stdout + stderr` and additionally require the index to exist and at least
one process to have printed a real result.
"""
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("sqlite_vec")

from center_kb import searchdb
from center_kb.hub import HubHandle

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
    # stream-agnostic: the F-C2 "client" branch prints to stdout (cli.py),
    # not stderr — checking stderr alone would miss it
    combined = [p.stdout + p.stderr for p in procs]
    assert not any("Traceback" in out for out in combined)
    assert not any("UNIQUE constraint failed" in out for out in combined)
    # the index must actually have been built, not just "no process crashed"
    assert db.exists()
    # at least one process must have found and printed a real result — the
    # "--- [" citation marker `kb query` prints per hit — so 5 processes that
    # all quietly found nothing (still exit 0) cannot pass this test
    assert any("--- [" in out for out in combined)


def test_forced_two_thread_race_is_idempotent(fed_hub):
    """Deterministic regression for the exact code path Step 5 changed —
    _sync_conn's per-repo BEGIN IMMEDIATE + fingerprint re-read-under-lock.

    test_five_concurrent_cold_builds_all_succeed above hits a race window
    measured in microseconds (this fixture's cold sync is a handful of FTS
    inserts) against real subprocess-startup jitter measured in tens to
    hundreds of milliseconds — across ~25 runs during this task's
    development it never once reproduced the original failure. This test
    forces the actual race instead of hoping OS scheduling finds it: two
    real sqlite3 connections, each on its own OS thread, are released into
    _sync_conn at the exact same instant by a threading.Barrier. Reverting
    Step 5's lock-and-recheck turns this into sqlite3.IntegrityError
    ("UNIQUE constraint failed") on every run (verified 5/5 while building
    this fix — see the task 4 report's TDD evidence).

    Bounded so a regression fails the test instead of hanging the suite:
    every barrier/join has an explicit timeout, and threads are daemons so a
    stuck worker cannot block interpreter exit either.
    """
    hub = HubHandle(root=fed_hub)

    # Bootstrap the schema SERIALLY first: this test targets only the
    # per-repo write-phase race in _sync_conn (Step 5). A forced-simultaneous
    # *cold* open (no schema yet) can separately raise "database is locked"
    # from _raw_connect's PRAGMA journal_mode=WAL — a real, pre-existing,
    # out-of-scope issue (see the task 4 report) that this test deliberately
    # does not exercise.
    bootstrap = searchdb.open_db(hub)
    bootstrap.close()

    errors: list[tuple[int, BaseException]] = []
    barrier = threading.Barrier(2, timeout=10)

    def worker(n: int) -> None:
        conn = None
        try:
            # sqlite3 connections are same-thread only — each worker opens
            # its own, against the now-warm (schema-created) db
            conn = searchdb.open_db(hub)
            barrier.wait()  # release both threads into _sync_conn together
            searchdb._sync_conn(conn, hub, None, vectors_strict=False)
        except BaseException as exc:  # capture for the assertion below, incl. BrokenBarrierError
            errors.append((n, exc))
        finally:
            if conn is not None:
                conn.close()

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)
    assert not any(t.is_alive() for t in threads), (
        "a worker thread is still running after 20s — this is a regression "
        "(a correct fix never blocks past the 10s barrier timeout), not a "
        "slow pass; failing instead of hanging the suite"
    )

    assert not errors, "\n".join(f"thread {n}: {exc!r}" for n, exc in errors)

    check = searchdb.open_db(hub)
    try:
        n_sections = check.execute("SELECT COUNT(*) FROM sections").fetchone()[0]
        n_repos = check.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
    finally:
        check.close()
    # the loser must have SKIPPED, not duplicated or under-written — this is
    # what "idempotent" means, not merely "didn't crash"
    assert n_sections == 2, f"expected 2 sections (1 per repo), got {n_sections}"
    assert n_repos == 2, f"expected 2 repos rows, got {n_repos}"
