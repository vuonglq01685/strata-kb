from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from center_kb import gitio

logger = logging.getLogger("center_kb.hub")

DEFAULT_TTL_SECONDS = 900  # 15 minutes — override with env CENTER_KB_HUB_TTL


@dataclass
class HubHandle:
    root: Path
    stale: bool = False
    age_seconds: float | None = None

    @property
    def kb_dir(self) -> Path:
        return self.root / ".kb"

    @property
    def federation_dir(self) -> Path:
        return self.root / "federation"


def _cache_base() -> Path:
    env = os.environ.get("CENTER_KB_HUB_CACHE")
    return Path(env) if env else Path.home() / ".center-kb" / "hub"


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

    cache = _cache_base() / hashlib.sha1(hub.encode("utf-8")).hexdigest()[:12]
    # Marker lives outside the clone directory: `commit_all` (publish, Task 4)
    # runs `git add -A` on the hub — if the marker were inside the clone it
    # would get added by mistake.
    marker = cache.parent / f"{cache.name}.last-pull"
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
        _touch_marker(marker)
        return HubHandle(root=cache)

    age = _marker_age(marker)
    if age is not None and age <= _ttl():
        return HubHandle(root=cache, age_seconds=age)
    try:
        gitio.pull(cache)
        _touch_marker(marker)
        return HubHandle(root=cache, age_seconds=0.0)
    except gitio.GitError as exc:
        logger.warning(
            "could not pull hub (offline?) — using stale cache (age ~%s seconds): %s",
            f"{age:.0f}" if age is not None else "?",
            exc,
        )
        return HubHandle(root=cache, stale=True, age_seconds=age)
