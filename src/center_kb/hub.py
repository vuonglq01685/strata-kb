from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import gitio

logger = logging.getLogger("center_kb.hub")

DEFAULT_TTL_SECONDS = 900  # 15 minutes — override with env CENTER_KB_HUB_TTL


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
    env = os.environ.get("CENTER_KB_HUB_CACHE")
    return Path(env) if env else Path.home() / ".center-kb" / "hub"


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
    return hashlib.sha1(stripped.encode("utf-8")).hexdigest()[:12]


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
    into its local config (gitio.py:136-154). A cache a pre-Task-12 version
    left behind never got that -- and a config change alone would not
    re-materialise files already checked out CRLF, so the only reliable fix
    is discarding it (F-D10 stays open on every existing install otherwise).

    `local=True` is load-bearing (Important 2): a merged read (the default
    `git config --get`) is satisfied by a global `core.autocrlf=false` even
    when the cache's OWN config never set it -- exactly the state an
    operator lands in after applying the F-D10 workaround by hand
    (`git config --global core.autocrlf false`). That machine's legacy
    caches would then look healthy forever and never get re-cloned.
    """
    return gitio.config_value(cache, "core.autocrlf", local=True) != "false"


def _discard_cache(cache: Path) -> None:
    """Remove a stale/legacy cache so `resolve_hub` re-clones it clean.

    The cache is disposable -- fully regenerable from the hub -- but the
    removal itself can fail: on Windows, one open handle anywhere under it
    (e.g. a `kb query`/MCP/web process still has `<cache>/.kb-work/
    search.sqlite3` open) is enough, and `_clear_readonly_and_retry`'s retry
    cannot help that. Before this wrap (Important 3) that OSError escaped
    `resolve_hub` raw for the first time ever -- `kb publish` printed a bare
    `[WinError 32] ...` naming no way forward, and intake's
    `_resolve_hub_or_503` turned a recoverable cache problem into an
    unhandled 500 instead of its usual 503. Re-raised as `gitio.GitError`:
    already caught everywhere `resolve_hub`'s other failures (clone/pull)
    are, and deliberately kept out of the `KbError` family (errors.py) since
    its handling is site-specific by design.

    onexc= (not onerror=, deprecated since 3.12) is used from 3.12 on; both
    callback shapes ignore their third argument, so `_clear_readonly_and_retry`
    works unchanged as either.
    """
    kwargs = (
        {"onexc": _clear_readonly_and_retry}
        if sys.version_info >= (3, 12)
        else {"onerror": _clear_readonly_and_retry}
    )
    try:
        shutil.rmtree(cache, **kwargs)
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
        return int(os.environ.get("CENTER_KB_HUB_TTL", DEFAULT_TTL_SECONDS))
    except ValueError:
        return DEFAULT_TTL_SECONDS


def _marker_age(marker: Path) -> float | None:
    try:
        return max(0.0, time.time() - float(marker.read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return None


def _touch_marker(marker: Path) -> None:
    marker.write_text(str(time.time()), encoding="utf-8")


def resolve_hub(hub: str) -> HubHandle | None:
    """Local path with a .kb/ → use it directly; otherwise clone/pull into the cache per TTL.

    None = the hub is unreachable and there is no cache yet — the caller
    continues with the local KB only (the hub is an enhancement, not a
    hard requirement).
    """
    direct = Path(hub)
    if direct.is_dir() and (direct / ".kb").is_dir():
        return HubHandle(root=direct.resolve())

    _, token = gitio.split_credentials(hub)
    cache = ensure_cache_base() / cache_key(hub)
    # Marker lives outside the clone directory: `commit_all` (publish, Task 4)
    # runs `git add -A` on the hub — if the marker were inside the clone it
    # would get added by mistake.
    marker = cache.parent / f"{cache.name}.last-pull"
    if cache.exists() and _cache_needs_reclone(cache):
        # A legacy (pre-Task-12) cache never got core.autocrlf=false written
        # locally -- repairing it in place (renormalise/checkout -f) risks a
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
                "could not clone hub '%s' — continuing with local KB only: %s",
                gitio.redact_url(hub),
                exc,
            )
            return None
        strip_remote_credentials(cache)
        _touch_marker(marker)
        return HubHandle(root=cache, token=token)

    strip_remote_credentials(cache)
    age = _marker_age(marker)
    if age is not None and age <= _ttl():
        return HubHandle(root=cache, age_seconds=age, token=token)
    try:
        gitio.pull(cache, hub)
        _touch_marker(marker)
        return HubHandle(root=cache, age_seconds=0.0, token=token)
    except gitio.GitError as exc:
        logger.warning(
            "could not pull hub (offline?) — using stale cache (age ~%s seconds): %s",
            f"{age:.0f}" if age is not None else "?",
            exc,
        )
        return HubHandle(root=cache, stale=True, age_seconds=age, token=token)
