"""hub — resolve a hub reference to a local checkout.

`resolve_hub` turns a hub ref (a local path with a `.kb/`, or a git URL) into
a HubHandle: a path used in place, or a clone cached under
~/.strata-kb/hub/<sha1 of the credential-free URL> and pulled when its TTL
marker expires. The cached clone never stores the credential; it travels on
the handle. Also owns the hub service's auto-pull thread (`pull_once`,
`start_auto_pull`). Clone/pull of one cache is serialised by a per-cache lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import stat
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from strata_kb import gitio

logger = logging.getLogger("strata_kb.hub")

DEFAULT_TTL_SECONDS = 900  # 15 minutes — override with env STRATA_KB_HUB_TTL
DEFAULT_PULL_INTERVAL_SECONDS = (
    300  # hub service auto-pull — env STRATA_KB_HUB_PULL_INTERVAL, 0 = off
)
PULL_TIMEOUT_SECONDS = 300  # a stalled fetch must not park the auto-pull thread forever
# Last pull outcome, for the hub UI. Under .git/: never committed, and it
# survives a hub service restart.
PULL_STATUS_FILE = "strata-kb-pull.json"


@dataclass
class HubHandle:
    root: Path
    stale: bool = False
    age_seconds: float | None = None
    # The hub ref's credential (None for ssh/local/public-https hubs) — carried
    # here, not in the clone's git config (strip_remote_credentials rewrites
    # that away), so every remote-touching gitio call can still authenticate.
    # repr=False is load-bearing: this dataclass reaches log lines and error
    # messages, and the default repr would print the token there.
    token: str | None = field(default=None, repr=False)

    @property
    def kb_dir(self) -> Path:
        return self.root / ".kb"

    @property
    def federation_dir(self) -> Path:
        return self.root / "federation"


def _cache_base() -> Path:
    env = os.environ.get("STRATA_KB_HUB_CACHE")
    return Path(env) if env else Path.home() / ".strata-kb" / "hub"


def ensure_cache_base() -> Path:
    base = _cache_base()
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)  # no-op on Windows, which ignores POSIX mode bits
    except OSError:  # pragma: no cover - exotic filesystems
        logger.debug("could not restrict %s to 0700", base)
    return base


def cache_key(hub: str) -> str:
    """Cache directory name for a hub ref, derived from the credential-free URL.

    Keying on the credentialed URL stranded the old clone -- with the old
    token inside it -- on every rotation.
    """
    stripped, _ = gitio.split_credentials(hub)
    return hashlib.sha1(stripped.encode("utf-8"), usedforsecurity=False).hexdigest()[
        :12
    ]


def strip_remote_credentials(root: Path) -> None:
    """Rewrite a cached clone's origin URL to its credential-free form."""
    current = gitio.remote_url(root)
    stripped, token = gitio.split_credentials(current)
    if token is None:
        return
    gitio._run(root, "remote", "set-url", "origin", stripped)


def _clear_readonly_and_retry(func, target, _exc_info) -> None:
    """shutil.rmtree onerror hook: git marks .git/objects/** read-only, which
    raises PermissionError on Windows (POSIX ignores the read-only bit for
    unlink) -- clear it and retry once rather than leaving a half-deleted
    cache directory behind."""
    os.chmod(target, stat.S_IWRITE)
    func(target)


def _cache_needs_reclone(cache: Path) -> bool:
    """A cache directory `clone()` created has core.autocrlf=false written
    into its local config (see gitio.clone). A cache an older version left
    behind never got that -- and a config change alone would not
    re-materialise files already checked out CRLF, so the only reliable fix
    is discarding it (otherwise every existing install keeps publishing a
    whole-tree diff every time).

    `local=True` is load-bearing: a merged read (the default `git config
    --get`) is satisfied by a global `core.autocrlf=false` even when the
    cache's OWN config never set it -- exactly the state an operator lands
    in after applying the CRLF workaround by hand (`git config --global
    core.autocrlf false`). That machine's legacy caches would then look
    healthy forever and never get re-cloned.
    """
    return gitio.config_value(cache, "core.autocrlf", local=True) != "false"


def _discard_cache(cache: Path) -> None:
    """Remove a stale/legacy cache so `resolve_hub` re-clones it clean.

    The cache is disposable -- fully regenerable from the hub -- but the
    removal itself can fail: on Windows, one open handle anywhere under it
    (e.g. a `kb query`/MCP/web process still has `<cache>/.kb-work/
    search.sqlite3` open) is enough, and `_clear_readonly_and_retry`'s retry
    cannot help that. Left unwrapped, that OSError escapes `resolve_hub`
    raw -- `kb publish` prints a bare `[WinError 32] ...` naming no way
    forward, and intake's `_resolve_hub_or_503` turns a recoverable cache
    problem into an unhandled 500 instead of its usual 503. Re-raised as
    `gitio.GitError`:
    already caught everywhere `resolve_hub`'s other failures (clone/pull)
    are; anywhere it is not, the root CLI guard prints it as one line (a
    `KbError` since 1.15.0).

    onexc= (not onerror=, deprecated since 3.12) is used from 3.12 on; both
    callback shapes ignore their third argument, so `_clear_readonly_and_retry`
    works unchanged as either.
    """
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(cache, onexc=_clear_readonly_and_retry)
        else:
            shutil.rmtree(cache, onerror=_clear_readonly_and_retry)
    except OSError as exc:
        raise gitio.GitError(
            f"could not remove the stale hub cache at '{cache}': {exc} -- it "
            "is disposable (fully regenerated from the hub on the next run); "
            f"delete '{cache}' yourself and retry. A locked file is the "
            "common cause on Windows -- stop any `kb query`/mcp/web process "
            "that may still have one open under it (most likely "
            ".kb-work/search.sqlite3)"
        ) from exc


def _ttl() -> int:
    try:
        return int(os.environ.get("STRATA_KB_HUB_TTL", DEFAULT_TTL_SECONDS))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _marker_age(marker: Path) -> float | None:
    try:
        return max(0.0, time.time() - float(marker.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return None


def _touch_marker(marker: Path) -> None:
    # newline-exempt: TTL marker in the local hub cache (~/.strata-kb/hub),
    # outside the cloned repo -- never committed, never diffed.
    marker.write_text(str(time.time()), encoding="utf-8")


def read_pull_status(root: Path) -> dict | None:
    """{"ok_at": epoch} of the last good pull, plus "error"/"error_at" when a
    later pull failed. None = never recorded (or not readable)."""
    try:
        data = json.loads(
            (root / ".git" / PULL_STATUS_FILE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def record_pull(root: Path, error: str | None = None) -> None:
    """Persist a pull's outcome; a success clears any earlier error. Never raises."""
    now = time.time()
    if error is None:
        status: dict = {"ok_at": now}
    else:
        status = {**(read_pull_status(root) or {}), "error_at": now, "error": error}
    path = root / ".git" / PULL_STATUS_FILE
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(status), encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except (
        OSError
    ) as exc:  # .git is a file (worktree) or read-only -- the UI just shows less
        logger.debug("could not record hub pull status in %s: %s", root, exc)


_cache_locks: dict[str, threading.Lock] = {}
_cache_locks_guard = threading.Lock()


def _cache_lock(cache: Path) -> threading.Lock:
    with _cache_locks_guard:
        return _cache_locks.setdefault(str(cache), threading.Lock())


def resolve_hub(hub: str) -> HubHandle | None:
    """Local path with a .kb/ → use it directly; otherwise clone/pull into the cache per TTL.

    None = the hub is unreachable and there is no cache yet — callers must
    not read that as "continue with the local KB".

    The clone/pull branch holds a per-cache lock: MCP tools and the web
    routes run on worker threads, and two of them finding the TTL expired
    at once would run two `git pull`s in one checkout.
    """
    direct = Path(hub)
    if direct.is_dir() and (direct / ".kb").is_dir():
        return HubHandle(root=direct.resolve())

    _, token = gitio.split_credentials(hub)
    cache = ensure_cache_base() / cache_key(hub)
    with _cache_lock(cache):
        return _resolve_cached(hub, cache, token)


def _resolve_cached(hub: str, cache: Path, token: str | None) -> HubHandle | None:
    # Marker lives outside the clone directory: `commit_all` (publish)
    # runs `git add -A` on the hub — if the marker were inside the clone it
    # would get added by mistake.
    marker = cache.parent / f"{cache.name}.last-pull"
    if cache.exists() and _cache_needs_reclone(cache):
        # A legacy cache never got core.autocrlf=false written locally --
        # repairing it in place (renormalise/checkout -f) risks a
        # half-converted tree; discard and re-clone under the same key
        # instead, exactly as if it had never existed. A crashed publish
        # leaves at most an unpushed commit on a publish/<rid> branch inside
        # the cache -- fully regenerable from the child repo, and strictly
        # better than a cache that whole-tree-diffs on every publish.
        _discard_cache(cache)
    if not cache.exists():
        try:
            gitio.clone(hub, cache)
        except gitio.GitError as exc:
            logger.warning(
                "could not clone hub '%s' and no cache exists: %s — this is "
                "not a degraded-but-working state",
                gitio.redact_url(hub),
                exc,
            )
            return None
        strip_remote_credentials(cache)
        _touch_marker(marker)
        record_pull(cache)
        return HubHandle(root=cache, token=token)

    strip_remote_credentials(cache)
    age = _marker_age(marker)
    if age is not None and age <= _ttl():
        return HubHandle(root=cache, age_seconds=age, token=token)
    try:
        gitio.pull(cache, hub)
        _touch_marker(marker)
        record_pull(cache)
        return HubHandle(root=cache, age_seconds=0.0, token=token)
    except gitio.GitError as exc:
        record_pull(cache, error=str(exc))
        logger.warning(
            "could not pull hub (offline?) — using stale cache (age ~%s seconds): %s",
            f"{age:.0f}" if age is not None else "?",
            exc,
        )
        return HubHandle(root=cache, stale=True, age_seconds=age, token=token)


def pull_interval() -> int:
    """Seconds between hub-service auto-pulls; 0 (or negative) = off."""
    try:
        return max(
            0,
            int(
                os.environ.get(
                    "STRATA_KB_HUB_PULL_INTERVAL", DEFAULT_PULL_INTERVAL_SECONDS
                )
            ),
        )
    except ValueError:
        return DEFAULT_PULL_INTERVAL_SECONDS


def pull_once(hub: str) -> bool:
    """Fast-forward the served hub checkout from its origin. True = HEAD moved.

    A hub served from its own checkout (`--hub .`) never pulls in
    resolve_hub -- without this, a merged hub PR stayed invisible until the
    next intake publish happened to pull. `--ff-only` (gitio.pull): a
    hand-edited or diverged checkout raises GitError and is left untouched.
    """
    handle = resolve_hub(hub)
    if handle is None or not gitio.has_remote(handle.root):
        return False
    before = gitio.head_commit(handle.root)
    try:
        gitio.pull(handle.root, token=handle.token, timeout=PULL_TIMEOUT_SECONDS)
    except gitio.GitError as exc:
        record_pull(handle.root, error=str(exc))
        raise
    record_pull(handle.root)
    after = gitio.head_commit(handle.root)
    if after == before:
        return False
    logger.info("hub refreshed %s..%s", before, after)
    from strata_kb import embed, searchdb

    # Sync the search index now rather than on the next query, so the first
    # caller after a merge does not pay the embed cost.
    searchdb.open_fresh(handle, embed.default_embedder()).close()
    return True


def _auto_pull_tick(hub: str) -> None:
    try:
        pull_once(hub)
    except Exception as exc:  # noqa: BLE001 -- a dead daemon thread would stop refreshing silently
        logger.warning("hub auto-pull failed -- serving the current checkout: %s", exc)


def start_auto_pull(hub: str) -> threading.Thread | None:
    """Daemon thread running pull_once every pull_interval() seconds; None when off."""
    interval = pull_interval()
    if interval <= 0:
        return None

    def _loop() -> None:
        while True:
            time.sleep(interval)
            _auto_pull_tick(hub)

    thread = threading.Thread(target=_loop, name="hub-auto-pull", daemon=True)
    thread.start()
    logger.info("hub auto-pull every %ss (STRATA_KB_HUB_PULL_INTERVAL)", interval)
    return thread
