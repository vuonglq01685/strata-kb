"""`.kb/auto/run.lock`: one `kb auto run` per repo.

An OS lock (`flock` on POSIX, `msvcrt.locking` on Windows, the `usage.ledger`
pattern) held for the loop's lifetime, with the holder's pid inside for the
message only. The OS drops the lock when the holder dies, so a file left by a
crash or SIGKILL is never stale, and two runs started together cannot both win.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from strata_kb.autorun import state as autostate
from strata_kb.errors import KbError

LOCK_NAME = "run.lock"


def lock_path(kb_dir: Path) -> Path:
    return autostate.log_dir(kb_dir).parent / LOCK_NAME


def _try_lock(fh) -> bool:
    """Take an OS lock on the open lock file without waiting; False when
    another process holds it. Per-fd on both platforms, so a second attempt
    from the same process also fails (`msvcrt.locking` on nt, `flock` else,
    the `usage.ledger` pattern)."""
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fh) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _holder_pid(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def running_pid(kb_dir: Path) -> int | None:
    """The pid of a live `kb auto run` in this repo, or None. Probes the OS
    lock, so a lock file left by a dead process reads as not running."""
    path = lock_path(kb_dir)
    if not path.exists():
        return None
    with path.open("a+b") as fh:
        if _try_lock(fh):
            _unlock(fh)
            return None
    return _holder_pid(path) or -1


@contextmanager
def run_lock(kb_dir: Path) -> Iterator[Path]:
    """Hold `.kb/auto/run.lock` (an OS lock, pid inside for the message) for
    the loop's lifetime: a second `kb auto run` in the same repo refuses with
    KbError while the first is alive. The OS drops the lock when the holder
    dies, so a file left by a crash or SIGKILL is never stale, and two runs
    started together cannot both win."""
    path = lock_path(kb_dir)
    fh = path.open("a+b")
    try:
        if not _try_lock(fh):
            holder = _holder_pid(path)
            who = f" (pid {holder})" if holder else ""
            raise KbError(f"kb auto run is already running{who}")
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n".encode())
        fh.flush()
        try:
            yield path
        finally:
            _unlock(fh)
    finally:
        fh.close()
