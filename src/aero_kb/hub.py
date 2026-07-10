from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from aero_kb import gitio

logger = logging.getLogger("aero_kb.hub")

DEFAULT_TTL_SECONDS = 900  # 15 phút — override bằng env AERO_KB_HUB_TTL


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
    env = os.environ.get("AERO_KB_HUB_CACHE")
    return Path(env) if env else Path.home() / ".aero-kb" / "hub"


def _ttl() -> int:
    try:
        return int(os.environ.get("AERO_KB_HUB_TTL", DEFAULT_TTL_SECONDS))
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
    """Path local có .kb/ → dùng thẳng; ngược lại clone/pull vào cache theo TTL.

    None = không truy cập được hub và chưa có cache — caller chạy tiếp
    chỉ với KB cục bộ (hub là tăng cường, không phải điều kiện sống).
    """
    direct = Path(hub)
    if direct.is_dir() and (direct / ".kb").is_dir():
        return HubHandle(root=direct.resolve())

    cache = _cache_base() / hashlib.sha1(hub.encode("utf-8")).hexdigest()[:12]
    # Marker sống ngoài thư mục clone: `commit_all` (publish, Task 4) dùng
    # `git add -A` trên hub — nếu marker nằm trong clone nó sẽ bị add nhầm.
    marker = cache.parent / f"{cache.name}.last-pull"
    if not cache.exists():
        try:
            gitio.clone(hub, cache)
        except gitio.GitError as exc:
            logger.warning(
                "không clone được hub '%s' — chạy tiếp chỉ với KB cục bộ: %s", hub, exc
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
            "không pull được hub (offline?) — dùng cache cũ (tuổi ~%s giây): %s",
            f"{age:.0f}" if age is not None else "?",
            exc,
        )
        return HubHandle(root=cache, stale=True, age_seconds=age)
