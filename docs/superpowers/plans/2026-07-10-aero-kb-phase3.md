# AERO-KB Phase 3 (Scale) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** kb-hub federation (hub repo + `kb publish` + doctor checks) + remote HTTP MCP với bearer token + embedding search (sqlite-vec + fastembed) — theo spec `docs/superpowers/specs/2026-07-10-aero-kb-phase3-design.md`.

**Architecture:** Hub là repo Git thụ động, client tự merge (spec quyết định #1). Module mới `hub.py`/`federation.py`/`publish.py`/`embed.py` là adapter quanh engine hiện có; `query/resolve/doctor/kbcontext/mcp/cli/gitio` mở rộng, không đổi hành vi khi không có `--hub` (ràng buộc §14.5 spec).

**Tech Stack:** Python 3.11+, typer, pydantic v2, PyYAML, rank-bm25, mcp>=1.2 (FastMCP v1 — xem contingency đầu `src/aero_kb/mcp.py`), sqlite-vec + fastembed (optional group `[embed]`), pytest + anyio.

## Global Constraints

- Tương thích ngược tuyệt đối: block `kb-context` Phase 2 (không có `hub_version`) resolve nguyên vẹn; mọi lệnh chạy y hệt khi không có `--hub` (spec tiêu chí 5, §14.5).
- Hub là tăng cường: hub offline/lỗi → cảnh báo + chạy tiếp với KB cục bộ, không bao giờ chết vì hub (spec §5, §12).
- Embedding là tăng cường: thiếu `[embed]` → fallback BM25 + log, không lỗi (spec §14.4). Import fastembed/sqlite-vec phải **lười** (trong hàm).
- Collision doc-id local ↔ hub: **local thắng khi query**, doctor exit 1 + in hướng dẫn dọn dẹp (spec quyết định #5).
- HTTP transport: thiếu env `AERO_KB_HTTP_TOKEN` → từ chối khởi động (fail fast); sai/thiếu token → 401 (spec §10).
- `gitio.py` là chỗ duy nhất chạy subprocess git (ràng buộc Phase 2, giữ nguyên).
- Exit code doctor giữ quy ước: 0 sạch, 1 lỗi, 2 chỉ stale.
- Thông điệp lỗi/CLI bằng tiếng Việt, docstring tiếng Việt — theo style toàn codebase.
- Test: pytest, fixture git repo tạm qua `run_git` (conftest.py) — không mock git, không tải model embedding thật trong test (fake `Embedder` tiêm vào).
- Commit message: conventional commits tiếng Việt như lịch sử repo (`feat:`, `fix:`, `test:`, `docs:`).

---

### Task 1: Mở rộng `gitio.py` — clone/pull/commit/push

**Files:**
- Modify: `src/aero_kb/gitio.py` (thêm cuối file)
- Test: `tests/test_gitio.py` (thêm cuối file)

**Interfaces:**
- Consumes: `_run(root, *args)`, `GitError` đã có sẵn trong `gitio.py`.
- Produces (Task 2/4 dùng):
  - `clone(url: str, dest: Path) -> None` — raise `GitError` khi fail
  - `pull(root: Path) -> None` — `--ff-only`, raise `GitError` khi fail
  - `pull_rebase(root: Path) -> None` — raise `GitError` khi fail
  - `commit_all(root: Path, message: str) -> bool` — `add -A` + commit; `False` nếu không có gì thay đổi
  - `push(root: Path) -> None` — `push origin HEAD`, raise `GitError` khi fail
  - `has_remote(root: Path) -> bool`
  - `remote_url(root: Path) -> str` — URL origin hoặc `""`

- [ ] **Step 1: Viết test fail**

Thêm vào cuối `tests/test_gitio.py`:

```python
# --- Phase 3: clone/pull/commit/push ---


@pytest.fixture
def bare_origin(tmp_path, run_git):
    """Bare repo làm origin + một clone 'seed' đã commit 1 file."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    seed = tmp_path / "seed"
    run_git(tmp_path, "clone", str(bare), "seed")
    (seed / "a.txt").write_text("v1", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v1")
    run_git(seed, "push", "origin", "HEAD")
    return {"bare": bare, "seed": seed}


def test_clone_and_pull_roundtrip(tmp_path, run_git, bare_origin):
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v1"
    # origin có commit mới → pull thấy được
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("v2", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "v2")
    run_git(seed, "push", "origin", "HEAD")
    gitio.pull(dest)
    assert (dest / "a.txt").read_text(encoding="utf-8") == "v2"


def test_clone_bad_url_raises(tmp_path):
    with pytest.raises(gitio.GitError):
        gitio.clone(str(tmp_path / "khong-ton-tai"), tmp_path / "dest")


def test_commit_all_returns_false_when_clean(bare_origin, run_git):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    assert gitio.commit_all(seed, "no-op") is False


def test_commit_all_and_push(bare_origin, run_git, tmp_path):
    seed = bare_origin["seed"]
    run_git(seed, "config", "user.name", "test")
    run_git(seed, "config", "user.email", "test@test.local")
    (seed / "b.txt").write_text("new", encoding="utf-8")
    assert gitio.commit_all(seed, "them b") is True
    gitio.push(seed)
    check = tmp_path / "check"
    gitio.clone(str(bare_origin["bare"]), check)
    assert (check / "b.txt").exists()


def test_push_rejected_then_pull_rebase_recovers(tmp_path, run_git, bare_origin):
    # clone2 tụt hậu so với origin → push fail → pull_rebase → push OK
    dest = tmp_path / "clone2"
    gitio.clone(str(bare_origin["bare"]), dest)
    run_git(dest, "config", "user.name", "test")
    run_git(dest, "config", "user.email", "test@test.local")
    seed = bare_origin["seed"]
    (seed / "a.txt").write_text("upstream", encoding="utf-8")
    run_git(seed, "add", "-A")
    run_git(seed, "commit", "-m", "upstream")
    run_git(seed, "push", "origin", "HEAD")
    (dest / "c.txt").write_text("local", encoding="utf-8")
    gitio.commit_all(dest, "them c")
    with pytest.raises(gitio.GitError):
        gitio.push(dest)
    gitio.pull_rebase(dest)
    gitio.push(dest)


def test_has_remote_and_remote_url(bare_origin, fixture_kb, run_git):
    assert gitio.has_remote(bare_origin["seed"]) is True
    assert gitio.remote_url(bare_origin["seed"]).endswith("origin.git")
    root = fixture_kb.parent
    run_git(root, "init")
    assert gitio.has_remote(root) is False
    assert gitio.remote_url(root) == ""
```

Lưu ý: đầu file test đã có `import pytest` và `from aero_kb import gitio` (kiểm tra — nếu thiếu import nào thì thêm).

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_gitio.py -v -k "clone or commit_all or push or has_remote"`
Expected: FAIL — `AttributeError: module 'aero_kb.gitio' has no attribute 'clone'`

- [ ] **Step 3: Implement**

Thêm vào cuối `src/aero_kb/gitio.py`:

```python
def clone(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", url, str(dest)], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise GitError(f"clone '{url}' thất bại: {proc.stderr.strip()}")


def pull(root: Path) -> None:
    proc = _run(root, "pull", "--ff-only")
    if proc.returncode != 0:
        raise GitError(f"pull thất bại: {proc.stderr.strip()}")


def pull_rebase(root: Path) -> None:
    proc = _run(root, "pull", "--rebase")
    if proc.returncode != 0:
        raise GitError(f"pull --rebase thất bại: {proc.stderr.strip()}")


def commit_all(root: Path, message: str) -> bool:
    """`git add -A` + commit; False nếu working tree sạch (không có gì để commit)."""
    _run(root, "add", "-A")
    if not _run(root, "status", "--porcelain").stdout.strip():
        return False
    proc = _run(root, "commit", "-m", message)
    if proc.returncode != 0:
        raise GitError(f"commit thất bại: {proc.stderr.strip() or proc.stdout.strip()}")
    return True


def push(root: Path) -> None:
    proc = _run(root, "push", "origin", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"push thất bại: {proc.stderr.strip()}")


def has_remote(root: Path) -> bool:
    return _run(root, "remote", "get-url", "origin").returncode == 0


def remote_url(root: Path) -> str:
    proc = _run(root, "remote", "get-url", "origin")
    return proc.stdout.strip() if proc.returncode == 0 else ""
```

- [ ] **Step 4: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_gitio.py -v`
Expected: PASS toàn bộ (test cũ + mới)

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/gitio.py tests/test_gitio.py
git commit -m "feat: gitio — clone/pull/commit/push cho hub federation"
```

---

### Task 2: `hub.py` — resolve hub, clone cache, TTL, offline fallback

**Files:**
- Create: `src/aero_kb/hub.py`
- Test: `tests/test_hub.py`
- Modify: `tests/conftest.py` (thêm fixture `hub_worktree`)

**Interfaces:**
- Consumes: `gitio.clone/pull/GitError` (Task 1).
- Produces (Task 4/5/7/9/10 dùng):
  - `HubHandle` dataclass: `root: Path`, `stale: bool = False`, `age_seconds: float | None = None`; property `kb_dir -> Path` (`root/".kb"`), property `federation_dir -> Path` (`root/"federation"`)
  - `resolve_hub(hub: str) -> HubHandle | None` — path local có `.kb/` dùng thẳng; ngược lại clone/pull cache theo TTL; `None` = không truy cập được (caller chạy tiếp với KB cục bộ)
  - `DEFAULT_TTL_SECONDS = 900`
  - Env: `AERO_KB_HUB_CACHE` (base dir cache), `AERO_KB_HUB_TTL` (giây)

- [ ] **Step 1: Thêm fixture `hub_worktree` vào cuối `tests/conftest.py`**

```python
HUB_L2 = """## 5.3 Restrictive Airspace

Restrictive airspace records: designation, type, multiple code, level.

| Type | Meaning |
|---|---|
| P | Prohibited |
| R | Restricted |
"""


@pytest.fixture
def hub_worktree(tmp_path: Path, run_git) -> Path:
    """Hub repo worktree: .kb/ có 1 doc domain 'arinc-424' + đã git commit."""
    hub = tmp_path / "kb-hub"
    doc_dir = hub / ".kb" / "arinc-424"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch5-airspace.md").write_text(HUB_L2, encoding="utf-8")
    (doc_dir / "ch5-airspace.raw.md").write_text(HUB_L2, encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="arinc-424",
            title="ARINC 424",
            revision="Supplement 22",
            sections=[
                models.SectionEntry(
                    id="5.3",
                    title="Restrictive Airspace",
                    summary="Restrictive airspace: designation, type, multiple code.",
                    status="reviewed",
                    file="ch5-airspace",
                )
            ],
        ),
    )
    models.save_yaml_model(
        hub / ".kb" / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id="arinc-424",
                    title="ARINC 424",
                    revision="Supplement 22",
                    tags=["arinc424", "airspace"],
                    summary="Navigation database spec.",
                )
            ]
        ),
    )
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub
```

- [ ] **Step 2: Viết test fail — `tests/test_hub.py`**

```python
import time
from pathlib import Path

from aero_kb import hub


def _use_cache(monkeypatch, tmp_path: Path) -> Path:
    cache = tmp_path / "hub-cache"
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(cache))
    return cache


def test_direct_path_with_kb_used_as_is(hub_worktree):
    handle = hub.resolve_hub(str(hub_worktree))
    assert handle is not None
    assert handle.root == hub_worktree.resolve()
    assert handle.kb_dir == hub_worktree.resolve() / ".kb"
    assert handle.stale is False


def test_url_cloned_into_cache(monkeypatch, tmp_path, hub_worktree, run_git):
    cache = _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    handle = hub.resolve_hub(str(bare))
    assert handle is not None
    assert str(handle.root).startswith(str(cache))
    assert (handle.kb_dir / "index.yaml").exists()


def test_fresh_cache_skips_pull(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    h1 = hub.resolve_hub(str(bare))
    # origin có commit mới ngay sau đó
    (hub_worktree / "new.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "new")
    run_git(hub_worktree, "push", "origin", "HEAD")
    h2 = hub.resolve_hub(str(bare))  # marker còn tươi → không pull
    assert not (h2.root / "new.txt").exists()
    assert h1.root == h2.root


def test_expired_ttl_pulls(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    hub.resolve_hub(str(bare))
    (hub_worktree / "new.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "new")
    run_git(hub_worktree, "push", "origin", "HEAD")
    h2 = hub.resolve_hub(str(bare))
    assert (h2.root / "new.txt").exists()
    assert h2.stale is False


def test_offline_uses_stale_cache(monkeypatch, tmp_path, hub_worktree, run_git):
    _use_cache(monkeypatch, tmp_path)
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    hub.resolve_hub(str(bare))
    import shutil

    shutil.rmtree(bare)  # "offline"
    h2 = hub.resolve_hub(str(bare))
    assert h2 is not None
    assert h2.stale is True
    assert (h2.kb_dir / "index.yaml").exists()


def test_unreachable_without_cache_returns_none(monkeypatch, tmp_path):
    _use_cache(monkeypatch, tmp_path)
    assert hub.resolve_hub(str(tmp_path / "khong-ton-tai.git")) is None
```

- [ ] **Step 3: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_hub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.hub'` (hoặc ImportError)

- [ ] **Step 4: Implement — `src/aero_kb/hub.py`**

```python
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
_PULL_MARKER = ".aero-kb-last-pull"


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
    marker = cache / _PULL_MARKER
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
```

Lưu ý: marker `.aero-kb-last-pull` nằm trong thư mục clone nhưng là file untracked — không ảnh hưởng `commit_all` của publish vì publish chỉ chạy trên hub, và nếu bị commit nhầm cũng vô hại; tuy vậy để sạch, Task 4 sẽ thêm nó vào `.gitignore` của hub demo. KHÔNG commit marker từ code.

Điểm tinh tế: `commit_all` dùng `add -A` sẽ add cả marker. Để tránh, sửa `_touch_marker` ghi marker **ngoài** clone: đặt marker cạnh clone — `cache.with_suffix(".last-pull")`. Implement như sau thay cho 2 chỗ dùng `marker`:

```python
# trong resolve_hub, thay dòng khai báo marker:
    marker = cache.parent / f"{cache.name}.last-pull"
```

(giữ `_PULL_MARKER` bị xóa — không cần hằng số nữa; test không đụng tên file marker nên không đổi.)

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_hub.py tests/test_gitio.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/hub.py tests/test_hub.py tests/conftest.py
git commit -m "feat: hub — resolve kb-hub qua clone cache, TTL pull, offline fallback"
```

---

### Task 3: `federation.py` — đọc `federation/<repo>/` của hub

**Files:**
- Create: `src/aero_kb/federation.py`
- Test: `tests/test_federation.py`

**Interfaces:**
- Consumes: `models.KBIndex`, `models.Manifest`, `models.load_yaml_model`.
- Produces (Task 4/5/7/9 dùng):
  - `FederationMeta(BaseModel)`: `repo_id: str`, `source_url: str = ""`, `source_commit: str`, `published_at: str = ""`
  - `FederatedRepo` dataclass: `meta: FederationMeta`, `index: models.KBIndex`, `manifests: dict[str, models.Manifest]`
  - `load_federation(federation_dir: Path) -> list[FederatedRepo]` — bỏ qua entry hỏng kèm log warning, không raise

- [ ] **Step 1: Viết test fail — `tests/test_federation.py`**

```python
from pathlib import Path

from aero_kb import federation, models


def _write_entry(fed_dir: Path, repo_id: str, doc_id: str) -> None:
    entry = fed_dir / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        federation.FederationMeta(
            repo_id=repo_id,
            source_url=f"git@host:{repo_id}.git",
            source_commit="abc1234",
            published_at="2026-07-10T00:00:00+00:00",
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id=doc_id, title=doc_id, tags=["local"], summary=f"{doc_id} spec."
                )
            ]
        ),
    )
    models.save_yaml_model(
        entry / "manifests" / f"{doc_id}.yaml",
        models.Manifest(
            id=doc_id,
            title=doc_id,
            sections=[
                models.SectionEntry(
                    id="1.1",
                    title="Section One",
                    summary="Local mapping for domain records.",
                    status="reviewed",
                    file="ch1",
                )
            ],
        ),
    )


def test_load_two_repos(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "nav-data", "nav-mapping")
    _write_entry(fed, "crew-ops", "roster-sop")
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["crew-ops", "nav-data"]
    assert "roster-sop" in repos[0].manifests
    assert repos[0].manifests["roster-sop"].sections[0].id == "1.1"


def test_missing_dir_returns_empty(tmp_path):
    assert federation.load_federation(tmp_path / "khong-co") == []


def test_broken_entry_skipped(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "ok-repo", "ok-doc")
    bad = fed / "bad-repo"
    bad.mkdir()
    (bad / "_meta.yaml").write_text("::::", encoding="utf-8")
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["ok-repo"]


def test_broken_manifest_skipped_entry_kept(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "nav-data", "nav-mapping")
    (fed / "nav-data" / "manifests" / "hong.yaml").write_text("::::", encoding="utf-8")
    repos = federation.load_federation(fed)
    assert list(repos[0].manifests) == ["nav-mapping"]
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_federation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.federation'`

- [ ] **Step 3: Implement — `src/aero_kb/federation.py`**

```python
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from aero_kb import models

logger = logging.getLogger("aero_kb.federation")


class FederationMeta(BaseModel):
    repo_id: str
    source_url: str = ""
    source_commit: str
    published_at: str = ""


@dataclass
class FederatedRepo:
    meta: FederationMeta
    index: models.KBIndex
    manifests: dict[str, models.Manifest] = field(default_factory=dict)


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Đọc mọi entry federation/<repo>/ — entry hỏng bị bỏ qua kèm warning."""
    if not federation_dir.is_dir():
        return []
    repos: list[FederatedRepo] = []
    for child in sorted(p for p in federation_dir.iterdir() if p.is_dir()):
        meta_path = child / "_meta.yaml"
        index_path = child / "index.yaml"
        if not meta_path.exists() or not index_path.exists():
            logger.warning(
                "federation/%s thiếu _meta.yaml hoặc index.yaml — bỏ qua", child.name
            )
            continue
        try:
            meta = models.load_yaml_model(meta_path, FederationMeta)
            index = models.load_yaml_model(index_path, models.KBIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            logger.warning("federation/%s hỏng — bỏ qua: %s", child.name, exc)
            continue
        manifests: dict[str, models.Manifest] = {}
        for mf in sorted((child / "manifests").glob("*.yaml")):
            try:
                manifest = models.load_yaml_model(mf, models.Manifest)
            except (yaml.YAMLError, ValidationError) as exc:
                logger.warning(
                    "federation/%s manifest '%s' hỏng — bỏ qua: %s",
                    child.name,
                    mf.name,
                    exc,
                )
                continue
            manifests[manifest.id] = manifest
        repos.append(FederatedRepo(meta=meta, index=index, manifests=manifests))
    return repos
```

- [ ] **Step 4: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_federation.py -v`
Expected: PASS 4/4

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/federation.py tests/test_federation.py
git commit -m "feat: federation — model + reader cho federation/<repo>/ của hub"
```

---

### Task 4: `publish.py` + lệnh `kb publish`

**Files:**
- Create: `src/aero_kb/publish.py`
- Modify: `src/aero_kb/cli.py` (thêm command `publish`)
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `gitio` (Task 1), `hub.resolve_hub/HubHandle` (Task 2), `federation.FederationMeta` (Task 3), `models`.
- Produces:
  - `PublishError(RuntimeError)`
  - `PublishReport` dataclass: `repo_id: str`, `source_commit: str`, `n_docs: int`, `pushed: bool`
  - `publish(kb_dir: Path, hub_ref: str, repo_id: str | None = None, max_retries: int = 3) -> PublishReport`
  - CLI: `kb publish --hub <url|path> [--repo-id <id>]` (`--hub` đọc env `AERO_KB_HUB`); exit 0 OK, 1 lỗi

- [ ] **Step 1: Viết test fail — `tests/test_publish.py`**

```python
import pytest

from aero_kb import federation, gitio, models
from aero_kb.publish import PublishError, PublishReport, publish


@pytest.fixture
def hub_bare(tmp_path, hub_worktree, run_git):
    """Hub bare origin đã seed nội dung hub_worktree."""
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    return bare


def test_publish_to_hub_bare(monkeypatch, tmp_path, git_kb, hub_bare, run_git):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    report = publish(git_kb["kb"], str(hub_bare))
    assert isinstance(report, PublishReport)
    assert report.n_docs == 1
    assert report.pushed is True
    check = tmp_path / "check"
    gitio.clone(str(hub_bare), check)
    entry = check / "federation" / report.repo_id
    assert (entry / "index.yaml").exists()
    assert (entry / "manifests" / "demo-doc.yaml").exists()
    meta = models.load_yaml_model(entry / "_meta.yaml", federation.FederationMeta)
    assert meta.source_commit == gitio.head_commit(git_kb["root"])


def test_publish_direct_path_no_push(git_kb, hub_worktree):
    # hub là worktree path không remote → commit tại chỗ, pushed=False
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="repo-a")
    assert report.pushed is False
    assert (hub_worktree / "federation" / "repo-a" / "_meta.yaml").exists()


def test_repo_id_collides_with_domain_doc(git_kb, hub_worktree):
    with pytest.raises(PublishError, match="arinc-424"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="arinc-424")


def test_push_race_retries_with_rebase(
    monkeypatch, tmp_path, git_kb, hub_bare, run_git, hub_worktree
):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")  # tạo cache clone
    # origin tiến lên sau khi cache đã tươi (TTL mặc định 900s → lần 2 không pull)
    (hub_worktree / "race.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "race")
    run_git(hub_worktree, "push", "origin", "HEAD")
    # đổi .kb để publish lần 2 có diff → push đầu reject → rebase → OK
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Updated summary for race test."
    models.save_yaml_model(manifest_path, manifest)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "sua summary")
    report = publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")
    assert report.pushed is True
    check = tmp_path / "check2"
    gitio.clone(str(hub_bare), check)
    assert (check / "race.txt").exists()  # rebase giữ commit upstream
    text = (check / "federation" / "repo-a" / "manifests" / "demo-doc.yaml").read_text(
        encoding="utf-8"
    )
    assert "Updated summary" in text


def test_unreachable_hub_raises(tmp_path, git_kb, monkeypatch):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "khong-ton-tai.git"))
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_publish.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.publish'`

- [ ] **Step 3: Implement — `src/aero_kb/publish.py`**

```python
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from aero_kb import federation, gitio, models
from aero_kb import hub as hub_mod


class PublishError(RuntimeError):
    """Publish index lên hub thất bại."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool


def publish(
    kb_dir: Path, hub_ref: str, repo_id: str | None = None, max_retries: int = 3
) -> PublishReport:
    """Snapshot L0+L1 của repo hiện tại → federation/<repo-id>/ trên hub.

    Commit tại clone cache (hoặc worktree hub nếu --hub là path); push nếu
    hub có remote origin. Push bị reject (race giữa 2 CI) → pull --rebase
    rồi thử lại, tối đa max_retries lần.
    """
    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name

    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"không truy cập được hub '{hub_ref}'")

    hub_index_path = handle.kb_dir / "index.yaml"
    if hub_index_path.exists():
        hub_index = models.load_yaml_model(hub_index_path, models.KBIndex)
        if rid in {d.id for d in hub_index.docs}:
            raise PublishError(
                f"repo-id '{rid}' trùng doc-id tài liệu domain trong hub — "
                "chọn --repo-id khác"
            )

    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    dest = handle.federation_dir / rid
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "manifests").mkdir(parents=True)
    models.save_yaml_model(dest / "index.yaml", local_index)
    for doc in local_index.docs:
        manifest_path = kb_abs / doc.id / "_manifest.yaml"
        if manifest_path.exists():
            shutil.copyfile(manifest_path, dest / "manifests" / f"{doc.id}.yaml")
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=gitio.remote_url(source_root),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)

    committed = gitio.commit_all(handle.root, f"publish: {rid} @ {source_commit}")
    pushed = False
    if committed and gitio.has_remote(handle.root):
        for attempt in range(max_retries):
            try:
                gitio.push(handle.root)
                pushed = True
                break
            except gitio.GitError:
                if attempt == max_retries - 1:
                    raise PublishError(
                        f"push hub thất bại sau {max_retries} lần thử (race?)"
                    )
                gitio.pull_rebase(handle.root)
    return PublishReport(
        repo_id=rid,
        source_commit=source_commit,
        n_docs=len(local_index.docs),
        pushed=pushed,
    )
```

Lưu ý: commit trong cache clone cần git identity — CI/máy dev có sẵn; test dùng `hub_worktree` đã `git config user.name/email`, còn cache clone kế thừa global config của máy chạy test. Nếu CI không có global identity, thêm vào `gitio.commit_all` hai flag `-c user.name=aero-kb -c user.email=aero-kb@local` khi commit — chỉ làm nếu test CI fail vì thiếu identity.

- [ ] **Step 4: Thêm CLI command — `src/aero_kb/cli.py`**

Thêm sau command `stats` (trước `context_app` section):

```python
@app.command()
def publish(
    hub: str = typer.Option(
        ..., "--hub", envvar="AERO_KB_HUB", help="URL hoặc path kb-hub"
    ),
    repo_id: str = typer.Option(
        "", "--repo-id", help="ID repo trên hub (mặc định: tên thư mục git root)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Publish snapshot L0+L1 của repo này lên federation/<repo-id>/ trên hub."""
    from aero_kb import gitio
    from aero_kb.publish import PublishError
    from aero_kb.publish import publish as publish_kb

    try:
        report = publish_kb(kb_dir, hub, repo_id=repo_id or None)
    except (PublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "push" if report.pushed else "commit tại chỗ (hub không có remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )
```

- [ ] **Step 5: Test CLI — thêm vào cuối `tests/test_publish.py`**

```python
def test_cli_publish(git_kb, hub_worktree, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(
        app, ["publish", "--hub", str(hub_worktree), "--repo-id", "repo-a"]
    )
    assert result.exit_code == 0, result.output
    assert "repo-a" in result.output


def test_cli_publish_error_exit_1(git_kb, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(app, ["publish", "--hub", str(tmp_path / "x.git")])
    assert result.exit_code == 1
```

- [ ] **Step 6: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_publish.py -v`
Expected: PASS 7/7

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/publish.py src/aero_kb/cli.py tests/test_publish.py
git commit -m "feat: kb publish — snapshot L0+L1 lên hub, push retry khi race"
```

---

### Task 5: Query hợp nhất 3 lớp (local + hub + federation)

**Files:**
- Modify: `src/aero_kb/query.py`
- Modify: `src/aero_kb/cli.py` (query/get thêm `--hub`)
- Test: `tests/test_query_hub.py` (file mới — test query cũ giữ nguyên không đụng)

**Interfaces:**
- Consumes: `hub.HubHandle` (Task 2), `federation.load_federation` (Task 3).
- Produces (Task 10/12 dùng):
  - `QueryResult` thêm field `source: str = "local"` — giá trị `"local"` | `"hub"` | `"remote:<repo-id>"`
  - `search(kb_dir, text, tags=None, budget=2000, hub: HubHandle | None = None) -> list[QueryResult]`
  - `get_section(kb_dir, doc_id, section_id, level="l2", hub: HubHandle | None = None) -> QueryResult | None` — không thấy local thì tìm ở hub `.kb/`
  - Hành vi: kết quả remote có `content` = summary L1 + dòng con trỏ repo; citation dạng `<repo-id>:<doc> §<sec>`; collision doc-id local↔hub → local thắng

- [ ] **Step 1: Viết test fail — `tests/test_query_hub.py`**

```python
from aero_kb import models
from aero_kb.hub import HubHandle
from aero_kb.query import get_section, search


def _fed_entry(hub_root, repo_id, doc_id, summary):
    from aero_kb.federation import FederationMeta

    entry = hub_root / "federation" / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id=repo_id, source_url=f"git@host:{repo_id}.git", source_commit="abc1234"
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[models.IndexEntry(id=doc_id, title=doc_id, tags=["ops"], summary=summary)]
        ),
    )
    models.save_yaml_model(
        entry / "manifests" / f"{doc_id}.yaml",
        models.Manifest(
            id=doc_id,
            title=doc_id,
            sections=[
                models.SectionEntry(
                    id="3.2",
                    title="Roster Rules",
                    summary=summary,
                    status="reviewed",
                    file="ch3",
                )
            ],
        ),
    )


def test_search_without_hub_unchanged(fixture_kb):
    results = search(fixture_kb, "airspace designation")
    assert results
    assert all(r.source == "local" for r in results)


def test_search_includes_hub_domain_docs(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "restrictive airspace designation", hub=handle)
    hub_hits = [r for r in results if r.source == "hub"]
    assert hub_hits
    assert hub_hits[0].doc_id == "arinc-424"
    assert "Restrictive" in hub_hits[0].content  # full L2, không phải summary
    assert "arinc-424 §5.3" in hub_hits[0].citation


def test_search_federation_returns_summary_with_pointer(fixture_kb, hub_worktree):
    _fed_entry(hub_worktree, "crew-ops", "roster-sop", "Crew roster duty limits and rest rules.")
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "crew roster duty rest", hub=handle)
    remote = [r for r in results if r.source == "remote:crew-ops"]
    assert remote
    r = remote[0]
    assert r.citation.startswith("crew-ops:roster-sop §3.2")
    assert "duty limits" in r.content
    assert "[remote]" in r.content and "crew-ops" in r.content


def test_local_wins_doc_id_collision(fixture_kb, hub_worktree):
    # hub cũng có doc 'demo-doc' → query chỉ trả bản local
    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(
        models.IndexEntry(
            id="demo-doc", title="Demo (hub copy)", tags=["demo", "airspace"],
            summary="Hub copy of demo doc.",
        )
    )
    models.save_yaml_model(hub_kb / "index.yaml", index)
    (hub_kb / "demo-doc").mkdir()
    models.save_yaml_model(
        hub_kb / "demo-doc" / "_manifest.yaml",
        models.Manifest(
            id="demo-doc",
            title="Demo (hub copy)",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Airspace Records",
                    summary="HUB VERSION airspace records.", status="reviewed", file="ch1",
                )
            ],
        ),
    )
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "airspace records designation", hub=handle)
    demo_hits = [r for r in results if r.doc_id == "demo-doc"]
    assert demo_hits
    assert all(r.source == "local" for r in demo_hits)


def test_tag_filter_applies_across_sources(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    results = search(fixture_kb, "restrictive airspace", tags=["arinc424"], hub=handle)
    assert results
    assert all(r.source == "hub" for r in results)  # local doc không có tag arinc424


def test_get_section_falls_back_to_hub(fixture_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    assert get_section(fixture_kb, "arinc-424", "5.3") is None  # không hub → không thấy
    result = get_section(fixture_kb, "arinc-424", "5.3", hub=handle)
    assert result is not None
    assert result.source == "hub"
    assert "Restrictive" in result.content
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_query_hub.py -v`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'hub'` (và các fail tương tự)

- [ ] **Step 3: Implement — sửa `src/aero_kb/query.py`**

Thay toàn bộ nội dung file bằng bản dưới (giữ nguyên `_tokenize`, `_citation`, phần lọc BM25Plus baseline; refactor corpus thành `_Candidate` 3 nguồn):

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rank_bm25 import BM25Plus

from aero_kb import models
from aero_kb.mdutils import count_tokens, slice_section

if TYPE_CHECKING:
    from aero_kb.hub import HubHandle


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = "local"  # "local" | "hub" | "remote:<repo-id>"


@dataclass
class _Candidate:
    doc: models.IndexEntry
    sec: models.SectionEntry
    kb_dir: Path | None  # None = federation, không có L2 để nạp
    source: str
    citation: str
    pointer: str = ""  # dòng chỉ về repo nguồn (chỉ remote)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(doc: models.IndexEntry | models.Manifest, section_id: str) -> str:
    base = f"{doc.id} §{section_id}"
    return f"{base} ({doc.revision})" if doc.revision else base


def _filter_tags(
    docs: list[models.IndexEntry], tags: list[str] | None
) -> list[models.IndexEntry]:
    if not tags:
        return docs
    tagset = {t.strip().lower() for t in tags}
    return [
        d for d in docs
        if tagset & {t.lower() for t in d.tags} or d.id.lower() in tagset
    ]


def _local_candidates(
    kb_dir: Path, tags: list[str] | None, source: str = "local"
) -> list[_Candidate]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)
    out: list[_Candidate] = []
    for doc in _filter_tags(index.docs, tags):
        manifest_path = kb_dir / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            out.append(
                _Candidate(
                    doc=doc, sec=sec, kb_dir=kb_dir, source=source,
                    citation=_citation(doc, sec.id),
                )
            )
    return out


def _federation_candidates(
    hub: "HubHandle", tags: list[str] | None
) -> list[_Candidate]:
    from aero_kb.federation import load_federation

    out: list[_Candidate] = []
    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        for doc in _filter_tags(repo.index.docs, tags):
            manifest = repo.manifests.get(doc.id)
            if manifest is None:
                continue
            for sec in manifest.sections:
                base = f"{rid}:{doc.id} §{sec.id}"
                citation = f"{base} ({doc.revision})" if doc.revision else base
                pointer = (
                    f"[remote] repo '{rid}'"
                    + (f" ({repo.meta.source_url})" if repo.meta.source_url else "")
                    + " — chỉ có summary L1; đọc sâu tại repo nguồn."
                )
                out.append(
                    _Candidate(
                        doc=doc, sec=sec, kb_dir=None, source=f"remote:{rid}",
                        citation=citation, pointer=pointer,
                    )
                )
    return out


def _candidate_content(c: _Candidate) -> str | None:
    if c.kb_dir is None:
        return f"{c.sec.summary}\n\n{c.pointer}"
    l2_path = c.kb_dir / c.doc.id / f"{c.sec.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), c.sec.id)


def _gather_candidates(
    kb_dir: Path, tags: list[str] | None, hub: "HubHandle | None"
) -> list[_Candidate]:
    candidates = _local_candidates(kb_dir, tags)
    if hub is None:
        return candidates
    local_ids = {c.doc.id for c in candidates}
    # local thắng khi collision: đọc index local đầy đủ (không lọc tag) để chặn
    index_path = kb_dir / "index.yaml"
    if index_path.exists():
        local_ids |= {
            d.id for d in models.load_yaml_model(index_path, models.KBIndex).docs
        }
    hub_candidates = [
        c for c in _local_candidates(hub.kb_dir, tags, source="hub")
        if c.doc.id not in local_ids
    ]
    return candidates + hub_candidates + _federation_candidates(hub, tags)


def search(
    kb_dir: Path,
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    hub: "HubHandle | None" = None,
) -> list[QueryResult]:
    corpus = _gather_candidates(kb_dir, tags, hub)
    if not corpus:
        return []

    section_tokens = [_tokenize(f"{c.sec.title} {c.sec.summary}") for c in corpus]
    bm25 = BM25Plus(section_tokens)
    query_token_list = _tokenize(text)
    query_tokens = set(query_token_list)
    scores = bm25.get_scores(query_token_list)
    ranked = sorted(
        zip(corpus, section_tokens, scores), key=lambda triple: -triple[2]
    )

    results: list[QueryResult] = []
    used = 0
    for c, tokens, score in ranked:
        if score <= 0:
            break
        if not query_tokens & set(tokens):
            # BM25Plus adds an idf*delta baseline to every in-vocabulary
            # query term, so sections sharing zero tokens with the query
            # can still score > 0. Skip them explicitly.
            continue
        content = _candidate_content(c)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=c.doc.id,
                section_id=c.sec.id,
                title=c.sec.title,
                score=float(score),
                citation=c.citation,
                content=content,
                tokens=n_tokens,
                source=c.source,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _get_section_in(
    kb_dir: Path, doc_id: str, section_id: str, level: str, source: str
) -> QueryResult | None:
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
    suffix = ".raw.md" if level == "l3" else ".md"
    path = kb_dir / doc_id / f"{sec.file}{suffix}"
    if not path.exists():
        return None
    content = slice_section(path.read_text(encoding="utf-8"), section_id)
    if content is None:
        return None
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=sec.title,
        score=0.0,
        citation=_citation(manifest, section_id),
        content=content,
        tokens=count_tokens(content),
        source=source,
    )


def get_section(
    kb_dir: Path,
    doc_id: str,
    section_id: str,
    level: str = "l2",
    hub: "HubHandle | None" = None,
) -> QueryResult | None:
    section_id = section_id.lstrip("§")
    result = _get_section_in(kb_dir, doc_id, section_id, level, "local")
    if result is not None:
        return result
    if hub is not None and (hub.kb_dir / doc_id / "_manifest.yaml").exists():
        # local thắng: chỉ rơi xuống hub khi local không có doc này
        return _get_section_in(hub.kb_dir, doc_id, section_id, level, "hub")
    return None
```

- [ ] **Step 4: Chạy test xác nhận pass (cả test cũ)**

Run: `python -m pytest tests/test_query_hub.py tests/test_query.py tests/test_mcp.py -v`
Expected: PASS toàn bộ — test query cũ không đổi hành vi (hub=None)

- [ ] **Step 5: Nối `--hub` vào CLI query/get — sửa `src/aero_kb/cli.py`**

Command `query` — thêm option + wiring (thay thân hàm hiện tại):

```python
@app.command()
def query(
    text: str = typer.Argument(..., help="Câu truy vấn"),
    tags: str = typer.Option("", help="Tags lọc doc, phân cách bằng dấu phẩy"),
    budget: int = typer.Option(2000, help="Token budget cho nội dung trả về"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    hub: str = typer.Option(
        "", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub (rỗng = không dùng)"
    ),
) -> None:
    """Tag match → BM25 → trả section L2 trong budget, kèm citation."""
    from aero_kb.query import search

    handle = None
    if hub:
        from aero_kb.hub import resolve_hub

        handle = resolve_hub(hub)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(kb_dir, text, tags=tag_list, budget=budget, hub=handle)
    if not results:
        typer.echo("Không tìm thấy section phù hợp.")
        raise typer.Exit(0)
    for r in results:
        mark = " [remote]" if r.source.startswith("remote:") else ""
        typer.secho(
            f"--- [{r.citation}]{mark} score={r.score:.2f} ~{r.tokens}tk", bold=True
        )
        typer.echo(r.content)
        typer.echo("")
```

Command `get` — thêm option `hub` y hệt (khai báo option giống trên) và truyền `hub=handle` vào `get_section(...)`; phần còn lại giữ nguyên.

- [ ] **Step 6: Test CLI hub wiring — thêm vào cuối `tests/test_query_hub.py`**

```python
def test_cli_query_with_hub(fixture_kb, hub_worktree):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    result = CliRunner().invoke(
        app,
        ["query", "restrictive airspace", "--kb-dir", str(fixture_kb),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "arinc-424 §5.3" in result.output
```

- [ ] **Step 7: Chạy toàn bộ test, commit**

Run: `python -m pytest -x -q`
Expected: PASS toàn bộ

```bash
git add src/aero_kb/query.py src/aero_kb/cli.py tests/test_query_hub.py
git commit -m "feat: query hợp nhất local + hub + federation, local thắng collision"
```

---

### Task 6: `kbcontext.py` — trường `hub_version` + ref prefix repo

**Files:**
- Modify: `src/aero_kb/kbcontext.py`
- Test: `tests/test_kbcontext.py` (thêm cuối file)

**Interfaces:**
- Consumes: không có mới.
- Produces (Task 7/8 dùng):
  - `KBRef` thêm field `repo_id: str | None = None`; `__str__` in `repo:doc §sec` khi có repo_id
  - `KBContext` thêm field `hub_version: str | None = None`
  - `parse_ref` chấp nhận dạng `crew-ops:roster-sop §3.2`
  - `parse`/`render` đọc/ghi `hub_version` — block không có `hub_version` parse/render y hệt Phase 2 (byte-identical với render cũ)

- [ ] **Step 1: Viết test fail — thêm cuối `tests/test_kbcontext.py`**

```python
# --- Phase 3: hub_version + repo-prefixed refs ---


def test_parse_ref_with_repo_prefix():
    ref = kbcontext.parse_ref("crew-ops:roster-sop §3.2")
    assert ref.repo_id == "crew-ops"
    assert ref.doc_id == "roster-sop"
    assert ref.section_id == "3.2"
    assert str(ref) == "crew-ops:roster-sop §3.2"


def test_parse_ref_without_prefix_has_no_repo():
    ref = kbcontext.parse_ref("arinc-424 §5.3")
    assert ref.repo_id is None
    assert str(ref) == "arinc-424 §5.3"


def test_parse_block_with_hub_version():
    text = """kb-context:
  version: "4f2a91c"
  hub_version: "a3f9c21"
  refs:
    - arinc-424 §5.3
"""
    ctx = kbcontext.parse(text)
    assert ctx.version == "4f2a91c"
    assert ctx.hub_version == "a3f9c21"


def test_parse_block_without_hub_version_backward_compat():
    text = """kb-context:
  version: "4f2a91c"
  refs:
    - demo-doc §1.1
"""
    ctx = kbcontext.parse(text)
    assert ctx.hub_version is None


def test_render_with_hub_version_roundtrip():
    ctx = kbcontext.KBContext(
        version="4f2a91c",
        hub_version="a3f9c21",
        refs=[kbcontext.parse_ref("arinc-424 §5.3")],
        tags=["arinc424"],
    )
    rendered = kbcontext.render(ctx)
    assert 'hub_version: "a3f9c21"' in rendered
    assert kbcontext.parse(rendered).hub_version == "a3f9c21"


def test_render_without_hub_version_unchanged_format():
    ctx = kbcontext.KBContext(
        version="4f2a91c", refs=[kbcontext.parse_ref("demo-doc §1.1")]
    )
    rendered = kbcontext.render(ctx)
    assert "hub_version" not in rendered
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_kbcontext.py -v -k "hub_version or repo_prefix or prefix"`
Expected: FAIL — `AttributeError: repo_id` / ValidationError

- [ ] **Step 3: Implement — sửa `src/aero_kb/kbcontext.py`**

Sửa 4 chỗ:

```python
# 1) KBRef — thêm repo_id + __str__:
class KBRef(BaseModel):
    doc_id: str
    section_id: str
    repo_id: str | None = None

    def __str__(self) -> str:
        prefix = f"{self.repo_id}:" if self.repo_id else ""
        return f"{prefix}{self.doc_id} §{self.section_id}"


# 2) KBContext — thêm hub_version:
class KBContext(BaseModel):
    version: str
    hub_version: str | None = None
    refs: list[KBRef]
    tags: list[str] = Field(default_factory=list)


# 3) _REF_RE — cho phép prefix 'repo:' (một dấu hai chấm duy nhất):
_REF_RE = re.compile(
    r"^(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s+§?(?P<sec>\S+)$"
)


# 4) parse_ref — đọc group repo:
def parse_ref(text: str) -> KBRef:
    m = _REF_RE.match(" ".join(text.split()))
    if not m:
        raise KBContextError(
            f"ref '{text}' sai format — cần '<doc-id> §<section-id>', vd 'arinc-424 §5.3'"
        )
    return KBRef(
        doc_id=m.group("doc"), section_id=m.group("sec"), repo_id=m.group("repo")
    )
```

Trong `parse(...)`, sau khi đọc `version`, thêm:

```python
    hub_version_raw = payload.get("hub_version")
    hub_version = str(hub_version_raw).strip() if hub_version_raw else None
```

và truyền `hub_version=hub_version` vào `KBContext(...)` cuối hàm.

Trong `render(...)`, sau dòng version, thêm:

```python
    if ctx.hub_version:
        lines.append(f'  hub_version: "{ctx.hub_version}"')
```

(lines khởi tạo hiện tại là `["kb-context:", f'  version: "{ctx.version}"', "  refs:"]` — tách thành build tuần tự: `lines = ["kb-context:", f'  version: "{ctx.version}"']`, chèn `hub_version` nếu có, rồi `lines.append("  refs:")`.)

- [ ] **Step 4: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_kbcontext.py tests/test_cli_context.py -v`
Expected: PASS toàn bộ (test Phase 2 nguyên vẹn — bảo chứng tương thích ngược)

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/kbcontext.py tests/test_kbcontext.py
git commit -m "feat: kbcontext — hub_version optional + ref prefix repo, tương thích block cũ"
```

---

### Task 7: `resolve.py` — resolve hai nguồn theo `version` / `hub_version`

**Files:**
- Modify: `src/aero_kb/resolve.py`
- Modify: `src/aero_kb/mcp.py` + `src/aero_kb/cli.py` (đổi call site `render_resolved`)
- Test: `tests/test_resolve_hub.py` (file mới)

**Interfaces:**
- Consumes: `hub.HubHandle` (Task 2), `KBRef.repo_id`/`KBContext.hub_version` (Task 6), `_resolve_one` hiện có.
- Produces:
  - `ResolvedRef` thêm field `pinned_rev: str = ""` — rev thực tế dùng để pin ref đó (local version hoặc hub_version)
  - `resolve_refs(kb_dir: Path, ctx: KBContext, hub: HubHandle | None = None) -> list[ResolvedRef]`
  - `render_resolved(results: list[ResolvedRef]) -> str` — **đổi signature**: bỏ tham số `version`, dùng `r.pinned_rev` từng ref (2 call site: `mcp.py`, `cli.py`)
  - Routing per-ref: `ref.repo_id` → federation trong hub repo; doc có ở index local worktree → local (Phase 2); doc có ở index hub → hub; còn lại → đường local Phase 2 (giữ semantics broken/stale cũ)

- [ ] **Step 1: Viết test fail — `tests/test_resolve_hub.py`**

```python
import pytest

from aero_kb import gitio, kbcontext, models
from aero_kb.hub import HubHandle
from aero_kb.resolve import render_resolved, resolve_refs


def _ctx(version, *refs, hub_version=None):
    return kbcontext.KBContext(
        version=version,
        hub_version=hub_version,
        refs=[kbcontext.parse_ref(r) for r in refs],
    )


@pytest.fixture
def hub_git(hub_worktree, run_git):
    """Hub 2 commit: rev1 = bản gốc; rev2 (HEAD) = §5.3 sửa L2 (amendment)."""
    rev1 = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    l2 = hub_worktree / ".kb" / "arinc-424" / "ch5-airspace.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "designation, type, multiple code, level.",
            "designation, type, multiple code, level, NEW controlling agency.",
        ),
        encoding="utf-8",
    )
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub amendment")
    rev2 = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    return {"root": hub_worktree, "rev1": rev1, "rev2": rev2}


def test_local_ref_without_hub_unchanged(git_kb):
    ctx = _ctx(git_kb["rev1"], "demo-doc §1.1")
    results = resolve_refs(git_kb["kb"], ctx)
    assert results[0].status == "stale"  # amendment ở rev2 như fixture Phase 2
    assert results[0].pinned_rev == git_kb["rev1"]


def test_hub_ref_resolves_at_hub_version(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3", hub_version=hub_git["rev1"])
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    r = results[0]
    assert r.status == "stale"  # hub đã amendment sau khi pin
    assert r.pinned_rev == hub_git["rev1"]
    assert "NEW controlling agency" not in r.content  # đúng nội dung bản pin
    assert "Supplement 22" in r.citation


def test_hub_ref_ok_when_pinned_at_head(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3", hub_version=hub_git["rev2"])
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    assert results[0].status == "ok"


def test_hub_ref_missing_hub_version_broken(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(git_kb["rev2"], "arinc-424 §5.3")  # không có hub_version
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    assert results[0].status == "broken"
    assert "hub_version" in results[0].reason
    assert "kb context new" in results[0].reason


def test_hub_ref_without_hub_handle_broken_not_crash(git_kb):
    # block cite doc hub nhưng chạy không có --hub → broken theo đường local Phase 2
    ctx = _ctx(git_kb["rev1"], "arinc-424 §5.3", hub_version="abc1234")
    results = resolve_refs(git_kb["kb"], ctx)
    assert results[0].status == "broken"


def test_remote_ref_resolves_summary_from_federation(git_kb, hub_git, run_git):
    # tạo federation entry trong hub rồi commit — rev3 chứa federation
    hub_root = hub_git["root"]
    from aero_kb.federation import FederationMeta

    entry = hub_root / "federation" / "crew-ops"
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="crew-ops", source_url="git@host:crew-ops.git",
                       source_commit="abc1234"),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="roster-sop", title="Roster SOP")]),
    )
    models.save_yaml_model(
        entry / "manifests" / "roster-sop.yaml",
        models.Manifest(
            id="roster-sop", title="Roster SOP",
            sections=[models.SectionEntry(
                id="3.2", title="Roster Rules",
                summary="Crew roster duty limits and rest rules.",
                status="reviewed", file="ch3",
            )],
        ),
    )
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "federation crew-ops")
    rev3 = run_git(hub_root, "rev-parse", "--short", "HEAD")

    handle = HubHandle(root=hub_root)
    ctx = _ctx(git_kb["rev2"], "crew-ops:roster-sop §3.2", hub_version=rev3)
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    r = results[0]
    assert r.status == "ok"
    assert "duty limits" in r.content
    assert "[remote]" in r.content
    assert r.pinned_rev == rev3


def test_render_resolved_uses_per_ref_rev(git_kb, hub_git):
    handle = HubHandle(root=hub_git["root"])
    ctx = _ctx(
        git_kb["rev1"], "demo-doc §1.1", "arinc-424 §5.3", hub_version=hub_git["rev1"]
    )
    results = resolve_refs(git_kb["kb"], ctx, hub=handle)
    text = render_resolved(results)
    assert f"@ {git_kb['rev1']}" in text
    assert f"@ {hub_git['rev1']}" in text
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_resolve_hub.py -v`
Expected: FAIL — `TypeError: resolve_refs() got an unexpected keyword argument 'hub'`

- [ ] **Step 3: Implement — sửa `src/aero_kb/resolve.py`**

Sửa/thêm như sau (giữ nguyên `_broken`, `_worktree_section`, `_resolve_one` — chỉ thêm `pinned_rev` khi dựng `ResolvedRef`):

```python
# đầu file, thêm import (TYPE_CHECKING để tránh vòng import):
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from aero_kb.hub import HubHandle


# ResolvedRef — thêm field:
@dataclass
class ResolvedRef:
    ref: KBRef
    status: Status
    citation: str
    content: str
    tokens: int
    reason: str = ""
    pinned_rev: str = ""


# _broken — thêm pinned_rev optional:
def _broken(ref: KBRef, reason: str, pinned_rev: str = "") -> ResolvedRef:
    return ResolvedRef(
        ref=ref, status="broken", citation=str(ref), content="", tokens=0,
        reason=reason, pinned_rev=pinned_rev,
    )


# _resolve_one — 2 chỗ dựng ResolvedRef cuối hàm thêm pinned_rev=rev;
# các _broken(...) trong hàm thêm pinned_rev=rev.


# MỚI — resolve ref hub doc (tái dùng _resolve_one trên repo hub):
def _resolve_hub_ref(hub: "HubHandle", ctx: KBContext, ref: KBRef) -> ResolvedRef:
    if not ctx.hub_version:
        return _broken(
            ref,
            "block thiếu 'hub_version' mà ref trỏ tài liệu hub — "
            "chạy lại `kb context new` để pin hub",
        )
    try:
        root = gitio.git_root(hub.kb_dir)
    except gitio.GitError as exc:
        return _broken(ref, str(exc))
    return _resolve_one(hub.kb_dir, root, ctx.hub_version, ref)


# MỚI — resolve ref remote (federation, chỉ có summary L1):
def _resolve_remote_ref(hub: "HubHandle | None", ctx: KBContext, ref: KBRef) -> ResolvedRef:
    if hub is None:
        return _broken(ref, "ref trỏ repo khác nhưng không có --hub")
    if not ctx.hub_version:
        return _broken(
            ref,
            "block thiếu 'hub_version' mà ref trỏ repo khác — "
            "chạy lại `kb context new` để pin hub",
        )
    rev = ctx.hub_version
    try:
        root = gitio.git_root(hub.root)
        manifest_text = gitio.read_at(
            root, rev,
            hub.federation_dir / ref.repo_id / "manifests" / f"{ref.doc_id}.yaml",
        )
    except gitio.GitError as exc:
        return _broken(ref, str(exc), pinned_rev=rev)
    if manifest_text is None:
        return _broken(
            ref,
            f"repo '{ref.repo_id}' chưa publish doc '{ref.doc_id}' tại rev {rev}",
            pinned_rev=rev,
        )
    try:
        manifest = models.Manifest.model_validate(yaml.safe_load(manifest_text) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        return _broken(
            ref, f"manifest federation hỏng tại rev {rev}: {exc}", pinned_rev=rev
        )
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return _broken(
            ref,
            f"§{ref.section_id} không có trong index đã publish của '{ref.repo_id}' "
            f"tại rev {rev}",
            pinned_rev=rev,
        )
    pinned_summary = sec.summary
    # freshness: so với summary trong federation worktree hiện tại của hub
    now_summary = None
    now_path = hub.federation_dir / ref.repo_id / "manifests" / f"{ref.doc_id}.yaml"
    if now_path.exists():
        try:
            now_manifest = models.load_yaml_model(now_path, models.Manifest)
            now_sec = next(
                (s for s in now_manifest.sections if s.id == ref.section_id), None
            )
            now_summary = now_sec.summary if now_sec else None
        except (yaml.YAMLError, ValidationError):
            now_summary = None
    if now_summary is None:
        status: Status = "stale"
        reason = "section không còn trong index federation hiện tại"
    elif now_summary.strip() != pinned_summary.strip():
        status = "stale"
        reason = "summary đã đổi trên hub sau khi pin (repo nguồn đã re-publish)"
    else:
        status = "ok"
        reason = ""
    citation = f"{ref} ({manifest.revision})" if manifest.revision else str(ref)
    content = (
        f"{pinned_summary}\n\n[remote] repo '{ref.repo_id}' — chỉ có summary L1; "
        "đọc sâu tại repo nguồn."
    )
    return ResolvedRef(
        ref=ref, status=status, citation=citation, content=content,
        tokens=count_tokens(content), reason=reason, pinned_rev=rev,
    )


def _doc_ids(kb_dir: Path) -> set[str]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return set()
    try:
        return {d.id for d in models.load_yaml_model(index_path, models.KBIndex).docs}
    except (yaml.YAMLError, ValidationError):
        return set()


def resolve_refs(
    kb_dir: Path, ctx: KBContext, hub: "HubHandle | None" = None
) -> list[ResolvedRef]:
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if hub is None:
        # đường Phase 2 nguyên vẹn (ref remote → broken vì repo_id không có local)
        return [
            _resolve_remote_ref(None, ctx, ref) if ref.repo_id
            else _resolve_one(kb_abs, root, ctx.version, ref)
            for ref in ctx.refs
        ]
    local_ids = _doc_ids(kb_abs)
    hub_ids = _doc_ids(hub.kb_dir)
    out: list[ResolvedRef] = []
    for ref in ctx.refs:
        if ref.repo_id:
            out.append(_resolve_remote_ref(hub, ctx, ref))
        elif ref.doc_id in local_ids or ref.doc_id not in hub_ids:
            # local thắng collision; doc lạ → đường local Phase 2 (broken/stale cũ)
            out.append(_resolve_one(kb_abs, root, ctx.version, ref))
        else:
            out.append(_resolve_hub_ref(hub, ctx, ref))
    return out


# render_resolved — ĐỔI SIGNATURE (bỏ version, dùng pinned_rev từng ref):
def render_resolved(results: list[ResolvedRef]) -> str:
    parts: list[str] = []
    for r in results:
        rev = r.pinned_rev or "?"
        parts.append(f"--- [{r.citation} @ {rev}] status={r.status} ~{r.tokens}tk")
        if r.status == "broken":
            parts.append(f"!! {r.reason}")
        elif r.status == "stale":
            parts.append(
                f"!! {r.reason} — chạy `kb diff {r.ref.doc_id} --against {rev}` "
                "để xem thay đổi"
            )
        if r.content:
            parts.append(r.content)
        parts.append("")
    return "\n".join(parts).strip()
```

Lưu ý `_resolve_one` khi ref remote đi đường local: `ref.doc_id` không có manifest → broken "doc không tồn tại tại rev" — chấp nhận được, nhưng test `test_hub_ref_without_hub_handle_broken_not_crash` chỉ cần broken. Riêng ref có `repo_id` khi `hub is None` phải qua `_resolve_remote_ref(None, ...)` để có thông điệp đúng.

- [ ] **Step 4: Sửa 2 call site `render_resolved`**

`src/aero_kb/mcp.py` — trong `kb_resolve`: `return render_resolved(results)` (bỏ `ctx.version`).
`src/aero_kb/cli.py` — command `resolve`: `typer.echo(render_resolved(results))`.

- [ ] **Step 5: Chạy test xác nhận pass (cả Phase 2)**

Run: `python -m pytest tests/test_resolve_hub.py tests/test_resolve.py tests/test_mcp.py tests/test_phase2_e2e.py -v`
Expected: PASS toàn bộ. Nếu test Phase 2 nào assert format output có version — cập nhật assertion theo `pinned_rev` (giá trị hiển thị không đổi với block thuần local vì `pinned_rev == ctx.version`).

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/resolve.py src/aero_kb/mcp.py src/aero_kb/cli.py tests/test_resolve_hub.py
git commit -m "feat: resolve hai nguồn — ref hub theo hub_version, ref remote qua federation"
```

---

### Task 8: CLI `context new` / `resolve` / `doctor` học `--hub`

**Files:**
- Modify: `src/aero_kb/cli.py` (`context_new`, `resolve`, `doctor` — thêm option `--hub`)
- Modify: `src/aero_kb/doctor.py` (`check_context` nhận `hub`)
- Test: `tests/test_cli_hub.py` (file mới)

**Interfaces:**
- Consumes: `hub.resolve_hub` (Task 2), `query.get_section(hub=...)` (Task 5), `resolve_refs(hub=...)` (Task 7), `kbcontext.KBContext.hub_version` (Task 6).
- Produces:
  - `kb context new --refs ... [--hub <url|path>]` — ref hub/remote hợp lệ, block có `hub_version` khi có ref ngoài local
  - `kb resolve <file|-> [--hub ...]`, `kb doctor [--context ...] [--hub ...]`
  - `doctor.check_context(kb_dir, text, hub: HubHandle | None = None)` — chuyển hub xuống `resolve_refs`
  - Mọi option `--hub` đọc env `AERO_KB_HUB`

- [ ] **Step 1: Viết test fail — `tests/test_cli_hub.py`**

```python
from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_context_new_with_hub_ref_pins_hub_version(git_kb, hub_worktree, run_git, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §5.3",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert f'hub_version: "{hub_head}"' in result.output


def test_context_new_local_only_has_no_hub_version(git_kb, hub_worktree, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "hub_version" not in result.output


def test_context_new_bad_hub_ref_exit_1(git_kb, hub_worktree, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §9.9",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 1


def test_resolve_cli_with_hub(git_kb, hub_worktree, run_git, tmp_path, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    ticket = tmp_path / "ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{git_kb["rev2"]}"\n'
        f'  hub_version: "{hub_head}"\n  refs:\n    - arinc-424 §5.3\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"]),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "status=ok" in result.output


def test_doctor_context_with_hub(git_kb, hub_worktree, run_git, tmp_path, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    ticket = tmp_path / "ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{git_kb["rev2"]}"\n'
        f'  hub_version: "{hub_head}"\n  refs:\n    - arinc-424 §5.3\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--kb-dir", str(git_kb["kb"]), "--context", str(ticket),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_cli_hub.py -v`
Expected: FAIL — `Error: No such option: --hub` (exit code 2 của typer)

- [ ] **Step 3: Implement**

**a) `src/aero_kb/cli.py`** — helper dùng chung, đặt sau `app.add_typer(...)`:

```python
def _resolve_hub_option(hub: str):
    """'' → None; ngược lại resolve qua hub.resolve_hub (None nếu không truy cập được)."""
    if not hub:
        return None
    from aero_kb.hub import resolve_hub

    handle = resolve_hub(hub)
    if handle is None:
        typer.secho(
            f"[warn] không truy cập được hub '{hub}' — chạy tiếp với KB cục bộ",
            fg=typer.colors.YELLOW,
            err=True,
        )
    return handle
```

**b) `context_new`** — thêm option `hub: str = typer.Option("", "--hub", envvar="AERO_KB_HUB", help="URL/path kb-hub")`; thay khối validate refs:

```python
    handle = _resolve_hub_option(hub)
    bad: list[str] = []
    needs_hub = False
    for r in ref_list:
        if r.repo_id:
            found = handle is not None and (
                handle.federation_dir / r.repo_id / "manifests" / f"{r.doc_id}.yaml"
            ).exists()
            needs_hub = True
        else:
            found = get_section(kb_dir, r.doc_id, r.section_id) is not None
            if not found and handle is not None:
                found = (
                    get_section(kb_dir, r.doc_id, r.section_id, hub=handle) is not None
                )
                needs_hub = needs_hub or found
        if not found:
            bad.append(str(r))
    if bad:
        typer.secho(
            f"Ref không resolve được ở worktree: {', '.join(bad)}", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    hub_version = None
    if needs_hub and handle is not None:
        hub_version = gitio.head_commit(gitio.git_root(handle.root))
    ctx = kbcontext.KBContext(
        version=version, hub_version=hub_version, refs=ref_list, tags=tag_list
    )
```

(giữ nguyên cảnh báo `is_dirty` phía trên; `get_section` import sẵn trong hàm.)

**c) `resolve`** — thêm option `hub` như trên; `handle = _resolve_hub_option(hub)`; gọi `resolve_refs(kb_dir, ctx, hub=handle)`.

**d) `doctor`** — thêm option `hub`; `handle = _resolve_hub_option(hub)`; gọi `check_context(kb_dir, text, hub=handle)`.

**e) `src/aero_kb/doctor.py`** — `check_context` thêm tham số:

```python
def check_context(
    kb_dir: Path, text: str, hub: "HubHandle | None" = None
) -> tuple[list[Issue], list[ResolvedRef]]:
    ...
    results = resolve_refs(kb_dir, ctx, hub=hub)
```

kèm import `TYPE_CHECKING` cho `HubHandle` như các module khác.

- [ ] **Step 4: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_cli_hub.py tests/test_cli_context.py tests/test_cli_doctor_diff.py -v`
Expected: PASS toàn bộ

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/cli.py src/aero_kb/doctor.py tests/test_cli_hub.py
git commit -m "feat: cli — context new/resolve/doctor nhận --hub, pin hub_version khi cite hub"
```

---

### Task 9: `kb doctor` — kiểm tra hub (cache stale, index lệch, collision)

**Files:**
- Modify: `src/aero_kb/doctor.py` (thêm `check_hub`)
- Modify: `src/aero_kb/cli.py` (doctor wiring `check_hub` + exit 2 khi hub stale)
- Test: `tests/test_doctor_hub.py` (file mới)

**Interfaces:**
- Consumes: `hub.HubHandle` (Task 2), `federation.load_federation` (Task 3), `gitio.head_commit/git_root`, `models`.
- Produces:
  - `check_hub(kb_dir: Path, handle: HubHandle | None, repo_id: str | None = None) -> tuple[list[Issue], bool]` — trả (issues, hub_stale)
  - Quy tắc: handle None → warning "không truy cập được"; `handle.stale` → warning + hub_stale=True (CLI exit 2); collision doc-id local↔hub → **error kèm hướng dẫn dọn dẹp** (spec quyết định #5, phần tối ưu); `federation/<repo-id>/_meta.source_commit` ≠ HEAD local → error "index lệch"; chưa publish → warning; doc-id trùng giữa hai repo federation → warning

- [ ] **Step 1: Viết test fail — `tests/test_doctor_hub.py`**

```python
from aero_kb import gitio, models
from aero_kb.doctor import check_hub
from aero_kb.federation import FederationMeta
from aero_kb.hub import HubHandle


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def _warnings(issues):
    return [i.message for i in issues if i.level == "warning"]


def _fed_entry(hub_root, repo_id, source_commit, doc_id="local-doc"):
    entry = hub_root / "federation" / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id=repo_id, source_commit=source_commit),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id=doc_id, title=doc_id)]),
    )


def test_hub_unreachable_is_warning(git_kb):
    issues, stale = check_hub(git_kb["kb"], None)
    assert not _errors(issues)
    assert any("không truy cập được" in w for w in _warnings(issues))
    assert stale is False


def test_hub_stale_cache_flags_stale(git_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree, stale=True, age_seconds=3600.0)
    issues, stale = check_hub(git_kb["kb"], handle)
    assert stale is True
    assert any("cache" in w for w in _warnings(issues))


def test_collision_local_hub_is_error_with_guidance(git_kb, hub_worktree):
    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(models.IndexEntry(id="demo-doc", title="Demo (hub)"))
    models.save_yaml_model(hub_kb / "index.yaml", index)
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle)
    collision = [e for e in _errors(issues) if "demo-doc" in e]
    assert collision
    # hướng dẫn dọn dẹp từng bước phải nằm trong thông điệp
    assert "xóa" in collision[0].lower()
    assert "kb context new" in collision[0]


def test_index_out_of_date_is_error(git_kb, hub_worktree):
    _fed_entry(hub_worktree, "repo-a", source_commit="0000000")
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert any("lệch" in e for e in _errors(issues))


def test_index_up_to_date_ok(git_kb, hub_worktree):
    head = gitio.head_commit(git_kb["root"])
    _fed_entry(hub_worktree, "repo-a", source_commit=head)
    handle = HubHandle(root=hub_worktree)
    issues, stale = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert not _errors(issues)
    assert stale is False


def test_not_published_is_warning(git_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="chua-publish")
    assert any("chưa publish" in w for w in _warnings(issues))


def test_federation_cross_collision_warning(git_kb, hub_worktree):
    head = gitio.head_commit(git_kb["root"])
    _fed_entry(hub_worktree, "repo-a", head, doc_id="shared-doc")
    _fed_entry(hub_worktree, "repo-b", "1111111", doc_id="shared-doc")
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert any("shared-doc" in w for w in _warnings(issues))
```

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_doctor_hub.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_hub'`

- [ ] **Step 3: Implement — thêm vào `src/aero_kb/doctor.py`**

```python
# đầu file thêm:
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aero_kb.hub import HubHandle


_COLLISION_GUIDE = (
    "doc '{doc}' có ở cả KB cục bộ lẫn hub — local đang thắng khi query. "
    "Dọn dẹp: (1) xóa thư mục .kb/{doc}/ và entry '{doc}' trong .kb/index.yaml; "
    "(2) commit; ref đã pin vẫn resolve theo version cũ; "
    "(3) `kb context new` từ đó sẽ tự pin qua hub_version."
)


def check_hub(
    kb_dir: Path, handle: "HubHandle | None", repo_id: str | None = None
) -> tuple[list[Issue], bool]:
    """Kiểm tra sức khỏe liên quan hub. Trả (issues, hub_stale)."""
    from aero_kb.federation import load_federation

    if handle is None:
        return (
            [Issue("warning", "không truy cập được hub — chạy với KB cục bộ")],
            False,
        )
    issues: list[Issue] = []
    hub_stale = False
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "không rõ"
        issues.append(
            Issue("warning", f"hub cache stale (không pull được, tuổi {age})")
        )
        hub_stale = True

    local_ids: set[str] = set()
    index_path = kb_dir / "index.yaml"
    if index_path.exists():
        local_ids = {
            d.id for d in models.load_yaml_model(index_path, models.KBIndex).docs
        }
    hub_index_path = handle.kb_dir / "index.yaml"
    hub_ids: set[str] = set()
    if hub_index_path.exists():
        hub_ids = {
            d.id for d in models.load_yaml_model(hub_index_path, models.KBIndex).docs
        }
    for doc in sorted(local_ids & hub_ids):
        issues.append(Issue("error", _COLLISION_GUIDE.format(doc=doc)))

    repos = load_federation(handle.federation_dir)
    if repo_id:
        entry = next((r for r in repos if r.meta.repo_id == repo_id), None)
        if entry is None:
            issues.append(
                Issue("warning", f"repo '{repo_id}' chưa publish index lên hub")
            )
        else:
            try:
                head = gitio.head_commit(gitio.git_root(kb_dir.resolve()))
            except gitio.GitError as exc:
                head = ""
                issues.append(Issue("warning", str(exc)))
            if head and entry.meta.source_commit != head:
                issues.append(
                    Issue(
                        "error",
                        f"index trên hub lệch: federation/{repo_id} pin "
                        f"{entry.meta.source_commit}, repo đang ở {head} — "
                        "CI publish fail hoặc chưa chạy (`kb publish` để đồng bộ)",
                    )
                )
    counts = Counter(d.id for r in repos for d in r.index.docs)
    for doc_id, n in sorted(counts.items()):
        if n > 1:
            issues.append(
                Issue(
                    "warning",
                    f"doc-id '{doc_id}' xuất hiện ở {n} repo federation — "
                    "query vẫn phân biệt được theo repo-id nhưng nên đổi tên",
                )
            )
    return issues, hub_stale
```

- [ ] **Step 4: Wiring CLI — sửa command `doctor` trong `src/aero_kb/cli.py`**

Thân hàm sau khi thêm option `hub` (Task 8) trở thành:

```python
    from aero_kb.doctor import check_context, check_hub, check_kb

    issues = check_kb(kb_dir)
    handle = _resolve_hub_option(hub)
    hub_stale = False
    if hub:  # chỉ check hub khi được khai --hub / env AERO_KB_HUB
        repo_root_name = None
        try:
            from aero_kb import gitio as _gitio

            repo_root_name = _gitio.git_root(kb_dir.resolve()).name
        except Exception:
            pass
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_root_name)
        issues += hub_issues
    has_stale = False
    if context is not None:
        text = sys.stdin.read() if context == "-" else Path(context).read_text(
            encoding="utf-8"
        )
        ctx_issues, results = check_context(kb_dir, text, hub=handle)
        issues += ctx_issues
        has_stale = any(r.status == "stale" for r in results)

    for issue in issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"[{issue.level}] {issue.message}", fg=color)
    if any(i.level == "error" for i in issues):
        raise typer.Exit(1)
    if has_stale or hub_stale:
        raise typer.Exit(2)
    typer.echo("kb doctor: OK")
```

(`except Exception` quanh `git_root`: doctor phải chạy được cả ngoài git repo — `check_kb` thuần filesystem; giữ hành vi Phase 2.)

- [ ] **Step 5: Test CLI exit codes — thêm cuối `tests/test_doctor_hub.py`**

```python
def test_cli_doctor_hub_collision_exit_1(git_kb, hub_worktree, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(models.IndexEntry(id="demo-doc", title="Demo (hub)"))
    models.save_yaml_model(hub_kb / "index.yaml", index)
    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)]
    )
    assert result.exit_code == 1
    assert "demo-doc" in result.output
```

- [ ] **Step 6: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_doctor_hub.py tests/test_doctor.py tests/test_cli_doctor_diff.py -v`
Expected: PASS toàn bộ

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/doctor.py src/aero_kb/cli.py tests/test_doctor_hub.py
git commit -m "feat: doctor — check hub stale, index lệch, collision kèm hướng dẫn dọn dẹp"
```

---

### Task 10: MCP — kích hoạt `--hub` + transport HTTP với bearer token

**Files:**
- Modify: `src/aero_kb/mcp.py`
- Test: `tests/test_mcp.py` (thêm cuối file) + `tests/test_mcp_http.py` (file mới)

**Interfaces:**
- Consumes: `hub.resolve_hub` (Task 2), `search/get_section(hub=...)` (Task 5), `resolve_refs(hub=...)` (Task 7).
- Produces:
  - `ServerConfig` thêm: `transport: str = "stdio"`, `host: str = "127.0.0.1"`, `port: int = 8321`
  - `parse_args` nhận `--transport {stdio,http}`, `--host`, `--port`
  - `BearerAuthMiddleware(app, token)` — ASGI middleware, thiếu/sai `Authorization: Bearer <token>` → 401 JSON
  - `create_http_app(config: ServerConfig, token: str)` — Starlette app (streamable HTTP của FastMCP) bọc middleware
  - `main()`: transport http mà thiếu env `AERO_KB_HTTP_TOKEN` → `SystemExit` với thông điệp rõ (fail fast)
  - 3 tool giữ nguyên signature; hub resolve **lười theo từng call** (TTL trong `hub.py` tự lo tần suất pull)

- [ ] **Step 1: Viết test fail — thêm cuối `tests/test_mcp.py`**

```python
# --- Phase 3: hub kích hoạt ---


def test_parse_args_transport_defaults():
    config = parse_args([])
    assert config.transport == "stdio"
    assert config.port == 8321


def test_parse_args_http():
    config = parse_args(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"])
    assert config.transport == "http"
    assert config.host == "0.0.0.0"
    assert config.port == 9000


@pytest.mark.anyio
async def test_kb_search_reaches_hub_docs(fixture_kb, hub_worktree):
    server = create_server(
        ServerConfig(kb_dir=fixture_kb, hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "arinc-424 §5.3" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_falls_back_to_hub(fixture_kb, hub_worktree):
    server = create_server(
        ServerConfig(kb_dir=fixture_kb, hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "arinc-424", "section": "5.3"}
        )
        assert "Restrictive" in _text(result)


def test_main_http_without_token_fails_fast(monkeypatch):
    from aero_kb.mcp import main

    monkeypatch.delenv("AERO_KB_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        main(["--transport", "http"])
```

- [ ] **Step 2: Viết test middleware — `tests/test_mcp_http.py`**

```python
import pytest

starlette = pytest.importorskip("starlette")

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from aero_kb.mcp import BearerAuthMiddleware


def _dummy_app():
    async def ok(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"])])


def _client(token="secret-token"):
    return TestClient(BearerAuthMiddleware(_dummy_app(), token))


def test_missing_token_401():
    resp = _client().get("/mcp")
    assert resp.status_code == 401


def test_wrong_token_401():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer sai"})
    assert resp.status_code == 401


def test_correct_token_passes():
    resp = _client().get("/mcp", headers={"Authorization": "Bearer secret-token"})
    assert resp.status_code == 200
    assert resp.text == "ok"
```

Ghi chú: `starlette` là dependency bắc cầu của `mcp` — đã có sẵn trong env; `importorskip` phòng hờ. `TestClient` cần `httpx` (cũng là dep của `mcp`).

- [ ] **Step 3: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_mcp.py tests/test_mcp_http.py -v`
Expected: FAIL — `AttributeError: transport` / `ImportError: BearerAuthMiddleware`

- [ ] **Step 4: Implement — sửa `src/aero_kb/mcp.py`**

```python
# ServerConfig mở rộng:
@dataclass
class ServerConfig:
    kb_dir: Path
    hub: str | None = None
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8321


# trong create_server: helper resolve hub lười theo call (TTL do hub.py lo):
def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("aero-kb")

    def _hub():
        if not config.hub:
            return None
        from aero_kb.hub import resolve_hub

        return resolve_hub(config.hub)

    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Tìm section theo tag match + BM25; trả nội dung L2 trong token budget, kèm citation."""
        results = search(config.kb_dir, query, tags=tags, budget=budget, hub=_hub())
        if not results:
            return "Không tìm thấy section phù hợp — thử bỏ tags hoặc đổi từ khóa."
        return "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )

    @mcp.tool()
    def kb_get_section(doc: str, section: str, level: str = "l2") -> str:
        """Lấy chính xác một section: level 'l2' (cô đọng) hoặc 'l3' (nguyên văn)."""
        if level not in ("l2", "l3"):
            return f"level '{level}' không hợp lệ — dùng 'l2' hoặc 'l3'."
        result = get_section(config.kb_dir, doc, section, level=level, hub=_hub())
        if result is None:
            known = _known_docs(config.kb_dir)
            hint = f" Các doc hiện có: {known}." if known else ""
            return f"Không thấy {doc} §{section}.{hint}"
        return f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"

    @mcp.tool()
    def kb_resolve(kb_context: str) -> str:
        """Nhận block kb-context (hoặc nguyên văn ticket chứa block); trả các section đã cite đúng version pin + freshness ok/stale/broken."""
        try:
            ctx = kbcontext.parse(kb_context)
        except kbcontext.KBContextError as exc:
            return f"kb-context lỗi: {exc}"
        try:
            results = resolve_refs(config.kb_dir, ctx, hub=_hub())
        except gitio.GitError as exc:
            return f"git lỗi: {exc}"
        return render_resolved(results)

    return mcp


# MỚI — middleware ASGI:
class BearerAuthMiddleware:
    """Chặn mọi HTTP request thiếu/sai 'Authorization: Bearer <token>' → 401."""

    def __init__(self, app, token: str) -> None:
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
            if headers.get("authorization") != f"Bearer {self.token}":
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": b'{"error": "unauthorized"}',
                    }
                )
                return
        await self.app(scope, receive, send)


def create_http_app(config: ServerConfig, token: str):
    """Starlette app streamable HTTP của FastMCP, bọc bearer auth."""
    server = create_server(config)
    return BearerAuthMiddleware(server.streamable_http_app(), token)


# parse_args mở rộng:
def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m aero_kb.mcp", description="AERO-KB MCP server"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"), help="Thư mục KB")
    ap.add_argument("--hub", default=None, help="URL/path kb-hub (Phase 3)")
    ap.add_argument(
        "--transport", choices=("stdio", "http"), default="stdio",
        help="stdio (mặc định) hoặc http (streamable HTTP, cần AERO_KB_HTTP_TOKEN)",
    )
    ap.add_argument("--host", default="127.0.0.1", help="Host bind khi --transport http")
    ap.add_argument("--port", type=int, default=8321, help="Port khi --transport http")
    args = ap.parse_args(argv)
    return ServerConfig(
        kb_dir=args.kb, hub=args.hub, transport=args.transport,
        host=args.host, port=args.port,
    )


# main:
def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.transport == "http":
        import os

        token = os.environ.get("AERO_KB_HTTP_TOKEN", "")
        if not token:
            raise SystemExit(
                "thiếu env AERO_KB_HTTP_TOKEN — bắt buộc cho transport http "
                "(tài liệu có bản quyền, không chạy HTTP không auth)"
            )
        import uvicorn

        uvicorn.run(create_http_app(config, token), host=config.host, port=config.port)
        return
    create_server(config).run()
```

Xóa khối `if config.hub: logger.warning("... chưa kích hoạt ...")` cũ trong `main` — hub đã kích hoạt thật. Cập nhật test Phase 2 `test_parse_args_hub_kept_but_inactive` nếu tên còn ám chỉ "inactive": chỉ đổi tên test thành `test_parse_args_hub`, assertion giữ nguyên.

Ghi chú `streamable_http_app()`: FastMCP v1 (mcp>=1.2) expose method này trả Starlette app mount tại `/mcp`. Nếu version trong env đặt tên khác (`sse_app` là SSE cũ — KHÔNG dùng), kiểm tra bằng `python -c "from mcp.server.fastmcp import FastMCP; print([m for m in dir(FastMCP) if 'app' in m])"` và dùng method streamable HTTP tương ứng. `uvicorn` là dependency bắc cầu của `mcp` — nếu import fail, thêm `"uvicorn>=0.30"` vào dependencies trong `pyproject.toml`.

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_mcp.py tests/test_mcp_http.py -v`
Expected: PASS toàn bộ

- [ ] **Step 6: Smoke test HTTP end-to-end thủ công (không phải pytest)**

```bash
AERO_KB_HTTP_TOKEN=demo python -m aero_kb.mcp --kb .kb --transport http --port 8321 &
sleep 2
# thiếu token → 401
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8321/mcp
# có token → không phải 401 (406/400 tùy handshake MCP là OK — auth đã qua)
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8321/mcp \
  -H "Authorization: Bearer demo"
kill %1
```

Expected: dòng 1 in `401`, dòng 2 in mã khác `401`.

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/mcp.py tests/test_mcp.py tests/test_mcp_http.py
git commit -m "feat: mcp — kích hoạt --hub, transport http với bearer token fail-fast"
```

---

### Task 11: `embed.py` — index sqlite-vec, embedder tiêm được

**Files:**
- Create: `src/aero_kb/embed.py`
- Modify: `pyproject.toml` (optional group `[embed]`)
- Test: `tests/test_embed.py` (file mới, dùng fake embedder — không tải model)

**Interfaces:**
- Consumes: `models`, `mdutils.slice_section`.
- Produces (Task 12 dùng):
  - `Embedder` Protocol: `dim: int`; `embed(texts: list[str]) -> list[list[float]]`
  - `default_embedder() -> Embedder | None` — import lười fastembed; `None` + log khi thiếu `[embed]`
  - `ensure_index(kb_dir: Path, db_path: Path, embedder: Embedder) -> int` — build/refresh tăng dần theo content-hash; trả số section re-embed
  - `semantic_search(db_path: Path, embedder: Embedder, text: str, k: int = 10) -> list[tuple[str, str, float]]` — `(doc_id, section_id, score)` giảm dần; score = `1/(1+distance)`
  - `SEMANTIC_FALLBACK_THRESHOLD = 5.0` — ngưỡng BM25 top score; hằng số trung tính, tinh chỉnh khi đo thật (spec §7)

- [ ] **Step 1: Thêm optional group vào `pyproject.toml`**

```toml
[project.optional-dependencies]
ingest = ["docling>=2.0"]
dev = ["pytest>=8.0", "anyio>=4.0"]
embed = ["sqlite-vec>=0.1.6", "fastembed>=0.3"]
```

Chạy `pip install -e ".[dev,embed]"` trên máy dev (CI test không cần `[embed]` — test dùng fake, nhưng cần `sqlite-vec` để test index… **quyết định**: test index cần `sqlite-vec` thật (nhẹ, pure wheel ~2MB, không phải model); chỉ `fastembed` (model 100MB) mới bị fake. Thêm `sqlite-vec>=0.1.6` vào cả group `dev`.)

```toml
dev = ["pytest>=8.0", "anyio>=4.0", "sqlite-vec>=0.1.6"]
```

- [ ] **Step 2: Viết test fail — `tests/test_embed.py`**

```python
import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from aero_kb import embed


class FakeEmbedder:
    """Vector 4 chiều xác định trước theo từ khóa — không cần model thật."""

    dim = 4

    def embed(self, texts):
        out = []
        for t in texts:
            t = t.lower()
            out.append(
                [
                    1.0 if "airspace" in t else 0.0,
                    1.0 if "airway" in t else 0.0,
                    1.0 if "roster" in t else 0.0,
                    0.1,
                ]
            )
        return out


def test_ensure_index_builds_then_incremental(fixture_kb, tmp_path):
    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    n1 = embed.ensure_index(fixture_kb, db, fake)
    assert n1 == 2  # demo-doc có 2 section
    n2 = embed.ensure_index(fixture_kb, db, fake)
    assert n2 == 0  # không đổi → không re-embed


def test_ensure_index_reembeds_changed_section(fixture_kb, tmp_path):
    from aero_kb import models

    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Changed summary about airspace."
    models.save_yaml_model(manifest_path, manifest)
    assert embed.ensure_index(fixture_kb, db, fake) == 1


def test_semantic_search_ranks_by_similarity(fixture_kb, tmp_path):
    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    hits = embed.semantic_search(db, fake, "airspace designation rules")
    assert hits
    assert hits[0][0] == "demo-doc"
    assert hits[0][1] == "1.1"  # section airspace gần query hơn airway
    assert hits[0][2] > hits[-1][2] if len(hits) > 1 else True


def test_default_embedder_none_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastembed"):
            raise ImportError("no fastembed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert embed.default_embedder() is None
```

- [ ] **Step 3: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_embed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.embed'`

- [ ] **Step 4: Implement — `src/aero_kb/embed.py`**

```python
from __future__ import annotations

import hashlib
import logging
import sqlite3
import struct
from pathlib import Path
from typing import Protocol

from aero_kb import models
from aero_kb.mdutils import slice_section

logger = logging.getLogger("aero_kb.embed")

# Ngưỡng BM25 top-score kích hoạt bước 3 (embedding fallback) — hằng số
# trung tính, tinh chỉnh khi đo trên KB thật (spec Phase 3 §7).
SEMANTIC_FALLBACK_THRESHOLD = 5.0

_L2_HEAD_CHARS = 500  # phần đầu L2 đưa vào text embedding


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _FastEmbedder:
    """fastembed ONNX — bge-small-en-v1.5, 384 chiều, thuần local."""

    dim = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


def default_embedder() -> Embedder | None:
    """Embedder thật nếu đã cài [embed]; None (kèm log) nếu thiếu."""
    try:
        return _FastEmbedder()
    except ImportError:
        logger.info(
            "fastembed chưa cài — semantic search tắt, dùng BM25 "
            "(bật bằng: pip install -e '.[embed]')"
        )
        return None
    except Exception as exc:  # tải model fail (offline lần đầu...)
        logger.warning("không khởi tạo được embedder — fallback BM25: %s", exc)
        return None


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _connect(db_path: Path, dim: int) -> sqlite3.Connection:
    import sqlite_vec

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sections(
            id INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            section_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(doc_id, section_id)
        )"""
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_sections "
        f"USING vec0(embedding float[{dim}])"
    )
    return conn


def _section_text(kb_dir: Path, doc_id: str, sec: models.SectionEntry) -> str:
    text = f"{sec.title}\n{sec.summary}"
    l2_path = kb_dir / doc_id / f"{sec.file}.md"
    if l2_path.exists():
        content = slice_section(l2_path.read_text(encoding="utf-8"), sec.id)
        if content:
            text += "\n" + content[:_L2_HEAD_CHARS]
    return text


def ensure_index(kb_dir: Path, db_path: Path, embedder: Embedder) -> int:
    """Build/refresh index tăng dần theo content-hash. Trả số section re-embed."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return 0
    index = models.load_yaml_model(index_path, models.KBIndex)
    conn = _connect(db_path, embedder.dim)
    try:
        stored = {
            (row[1], row[2]): (row[0], row[3])
            for row in conn.execute(
                "SELECT id, doc_id, section_id, content_hash FROM sections"
            )
        }
        seen: set[tuple[str, str]] = set()
        to_embed: list[tuple[str, str, str, str]] = []  # doc, sec, hash, text
        for doc in index.docs:
            manifest_path = kb_dir / doc.id / "_manifest.yaml"
            if not manifest_path.exists():
                continue
            manifest = models.load_yaml_model(manifest_path, models.Manifest)
            for sec in manifest.sections:
                key = (doc.id, sec.id)
                seen.add(key)
                text = _section_text(kb_dir, doc.id, sec)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if key in stored and stored[key][1] == digest:
                    continue
                to_embed.append((doc.id, sec.id, digest, text))
        # xóa section không còn tồn tại
        for key, (rowid, _) in stored.items():
            if key not in seen:
                conn.execute("DELETE FROM sections WHERE id = ?", (rowid,))
                conn.execute("DELETE FROM vec_sections WHERE rowid = ?", (rowid,))
        if to_embed:
            vectors = embedder.embed([t[3] for t in to_embed])
            for (doc_id, sec_id, digest, _), vec in zip(to_embed, vectors):
                old = stored.get((doc_id, sec_id))
                if old is not None:
                    conn.execute("DELETE FROM sections WHERE id = ?", (old[0],))
                    conn.execute(
                        "DELETE FROM vec_sections WHERE rowid = ?", (old[0],)
                    )
                cur = conn.execute(
                    "INSERT INTO sections(doc_id, section_id, content_hash) "
                    "VALUES (?, ?, ?)",
                    (doc_id, sec_id, digest),
                )
                conn.execute(
                    "INSERT INTO vec_sections(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, _serialize(vec)),
                )
        conn.commit()
        return len(to_embed)
    finally:
        conn.close()


def semantic_search(
    db_path: Path, embedder: Embedder, text: str, k: int = 10
) -> list[tuple[str, str, float]]:
    """KNN trên index — trả (doc_id, section_id, score) giảm dần theo score."""
    if not db_path.exists():
        return []
    query_vec = embedder.embed([text])[0]
    conn = _connect(db_path, embedder.dim)
    try:
        rows = conn.execute(
            "SELECT s.doc_id, s.section_id, v.distance "
            "FROM vec_sections v JOIN sections s ON s.id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (_serialize(query_vec), k),
        ).fetchall()
    finally:
        conn.close()
    return [(doc, sec, 1.0 / (1.0 + dist)) for doc, sec, dist in rows]
```

- [ ] **Step 5: Chạy test xác nhận pass**

Run: `python -m pytest tests/test_embed.py -v`
Expected: PASS 4/4 (cần `pip install sqlite-vec` trong env dev trước — nằm trong group `dev` mới)

- [ ] **Step 6: Test model thật (đánh dấu slow, skip mặc định) — thêm cuối `tests/test_embed.py`**

```python
@pytest.mark.skipif(
    "not config.getoption('--run-slow', default=False)",
    reason="cần --run-slow (tải model ~100MB)",
)
def test_real_fastembed_roundtrip(fixture_kb, tmp_path):
    embedder = embed.default_embedder()
    if embedder is None:
        pytest.skip("fastembed chưa cài")
    db = tmp_path / "emb.db"
    embed.ensure_index(fixture_kb, db, embedder)
    hits = embed.semantic_search(db, embedder, "controlled airspace zones")
    assert hits and hits[0][0] == "demo-doc"
```

và thêm vào `tests/conftest.py`:

```python
def pytest_addoption(parser):
    parser.addoption(
        "--run-slow", action="store_true", default=False,
        help="chạy cả test tải model embedding thật",
    )
```

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/embed.py tests/test_embed.py tests/conftest.py pyproject.toml
git commit -m "feat: embed — index sqlite-vec tăng dần theo content-hash, embedder tiêm được"
```

---

### Task 12: Nối embedding vào query (bước 3 routing) + `--semantic` + build refresh

**Files:**
- Modify: `src/aero_kb/query.py` (fallback bước 3)
- Modify: `src/aero_kb/cli.py` (query `--semantic`; build refresh index)
- Test: `tests/test_query_semantic.py` (file mới)

**Interfaces:**
- Consumes: `embed.ensure_index/semantic_search/default_embedder/SEMANTIC_FALLBACK_THRESHOLD` (Task 11), `_gather_candidates`/`_candidate_content` (Task 5).
- Produces:
  - `search(..., semantic: bool = False, embedder: "Embedder | None" = None)` — hai tham số mới; `embedder` tiêm được cho test, mặc định `default_embedder()` khi cần
  - Kích hoạt bước 3 khi: `semantic=True` (ép) HOẶC BM25 không có kết quả HOẶC top score < `SEMANTIC_FALLBACK_THRESHOLD`
  - Index local tại `<kb_dir>/../.kb-work/embeddings.db` (cạnh `.kb/`); hub tại `<hub.root>/.kb-work/embeddings.db`
  - Semantic chỉ phủ local + hub `.kb/` (có L2); federation không tham gia (chỉ có summary — BM25 đã đủ)
  - `kb build` refresh index nếu file db đã tồn tại và embedder có sẵn

- [ ] **Step 1: Viết test fail — `tests/test_query_semantic.py`**

```python
from aero_kb.query import search

from tests.test_embed import FakeEmbedder  # tái dùng fake 4 chiều


def test_bm25_miss_falls_back_to_semantic(fixture_kb):
    # query không chung token nào với summary ("controlled zones") nhưng
    # FakeEmbedder map 'airspace' → trục 1 nên semantic vẫn bắt được
    results = search(
        fixture_kb, "airspace controlled zones", semantic=True,
        embedder=FakeEmbedder(),
    )
    assert results
    assert results[0].section_id == "1.1"


def test_semantic_flag_false_and_good_bm25_skips_embedding(fixture_kb):
    # embedder=None mà BM25 có kết quả tốt → không được đụng embedding
    results = search(fixture_kb, "airspace designation", embedder=None)
    assert results  # nguyên hành vi BM25


def test_no_embedder_no_crash_on_miss(fixture_kb):
    # BM25 miss hoàn toàn + không có embedder → trả rỗng, không exception
    results = search(fixture_kb, "zzz qqq xxx", embedder=None)
    assert results == []
```

Ghi chú import: nếu `tests/` không phải package (không có `__init__.py`), chuyển `FakeEmbedder` vào `tests/conftest.py` (không cần fixture, chỉ là class) và import `from conftest import FakeEmbedder` — chọn cách chạy được với pytest rootdir hiện tại.

- [ ] **Step 2: Chạy test xác nhận fail**

Run: `python -m pytest tests/test_query_semantic.py -v`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'semantic'`

- [ ] **Step 3: Implement — sửa `src/aero_kb/query.py`**

Thêm cuối phần import: `from aero_kb.embed import SEMANTIC_FALLBACK_THRESHOLD` (import module-level an toàn — `embed.py` không import fastembed ở module level).

Sửa `search(...)`:

```python
def search(
    kb_dir: Path,
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    hub: "HubHandle | None" = None,
    semantic: bool = False,
    embedder=None,  # aero_kb.embed.Embedder | None — tiêm được cho test
) -> list[QueryResult]:
    corpus = _gather_candidates(kb_dir, tags, hub)
    if not corpus:
        return []
    # ... (toàn bộ khối BM25 + vòng for hiện tại giữ nguyên, gom vào biến results)

    top_score = results[0].score if results else 0.0
    if semantic or not results or top_score < SEMANTIC_FALLBACK_THRESHOLD:
        semantic_results = _semantic_fallback(
            kb_dir, hub, corpus, text, budget, embedder
        )
        if semantic_results:
            return semantic_results
    return results
```

Thêm hàm mới cuối file:

```python
def _semantic_fallback(
    kb_dir: Path,
    hub: "HubHandle | None",
    corpus: list[_Candidate],
    text: str,
    budget: int,
    embedder,
) -> list[QueryResult]:
    """Bước 3 routing: KNN trên sqlite-vec, chỉ local + hub (có L2)."""
    from aero_kb import embed as embed_mod

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if embedder is None:
        return []
    by_key: dict[tuple[str, str, str], _Candidate] = {}
    for c in corpus:
        if c.kb_dir is not None:  # bỏ federation
            by_key[(c.source, c.doc.id, c.sec.id)] = c
    hits: list[tuple[str, str, str, float]] = []  # source, doc, sec, score
    stores: list[tuple[str, Path, Path]] = [
        ("local", kb_dir, kb_dir.resolve().parent / ".kb-work" / "embeddings.db")
    ]
    if hub is not None:
        stores.append(("hub", hub.kb_dir, hub.root / ".kb-work" / "embeddings.db"))
    for source, source_kb, db_path in stores:
        try:
            embed_mod.ensure_index(source_kb, db_path, embedder)
            for doc_id, sec_id, score in embed_mod.semantic_search(
                db_path, embedder, text
            ):
                hits.append((source, doc_id, sec_id, score))
        except Exception as exc:  # embedding là tăng cường — không bao giờ gãy query
            import logging

            logging.getLogger("aero_kb.query").warning(
                "semantic search lỗi (%s) — bỏ qua: %s", source, exc
            )
    results: list[QueryResult] = []
    used = 0
    for source, doc_id, sec_id, score in sorted(hits, key=lambda h: -h[3]):
        c = by_key.get((source, doc_id, sec_id))
        if c is None:
            continue
        content = _candidate_content(c)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=doc_id, section_id=sec_id, title=c.sec.title,
                score=float(score), citation=c.citation, content=content,
                tokens=n_tokens, source=c.source,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results
```

Lưu ý collision key: candidate hub bị loại khi trùng local id (Task 5) nên `by_key` không chứa bản hub — hit semantic từ db hub cho doc trùng sẽ không match key → tự động bị bỏ, đúng quy tắc local thắng.

- [ ] **Step 4: CLI — `--semantic` cho query + build refresh**

`query` command thêm option:

```python
    semantic: bool = typer.Option(
        False, "--semantic", help="Ép dùng embedding search (bước 3 routing)"
    ),
```

và truyền `semantic=semantic` vào `search(...)`.

`build` command — thêm cuối hàm (sau `typer.echo("kb build: OK")` KHÔNG đúng: refresh trước khi in OK, sau khi `report.ok`):

```python
    db_path = kb_dir.resolve().parent / ".kb-work" / "embeddings.db"
    if db_path.exists():
        from aero_kb.embed import default_embedder, ensure_index

        embedder = default_embedder()
        if embedder is not None:
            n = ensure_index(kb_dir, db_path, embedder)
            if n:
                typer.echo(f"embeddings.db: re-embed {n} section.")
    typer.echo("kb build: OK")
```

(spec §7: build chỉ làm tươi khi file đã tồn tại — không bắt CI tải model.)

- [ ] **Step 5: Chạy toàn bộ test**

Run: `python -m pytest -x -q`
Expected: PASS toàn bộ

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/query.py src/aero_kb/cli.py tests/test_query_semantic.py
git commit -m "feat: query — bước 3 embedding fallback theo ngưỡng BM25, cờ --semantic, build refresh index"
```

---

### Task 13: E2E federation — trọn vòng 2 repo + hub (tiêu chí 1, 2, 5)

**Files:**
- Test: `tests/test_phase3_e2e.py` (file mới)

**Interfaces:**
- Consumes: mọi thứ Task 1–9 (publish, query merge, context new, resolve, doctor).
- Produces: bằng chứng nghiệm thu tự động cho tiêu chí hoàn thành 1, 2, 5 của spec.

- [ ] **Step 1: Viết E2E test — `tests/test_phase3_e2e.py`**

```python
"""E2E Phase 3: đúng kịch bản demo-federation (spec §11) bằng tmp git repos.

hub bare ← publish từ repo-a (git_kb) và repo-b (tự dựng) →
query từ repo-a thấy: tài liệu domain hub (full L2) + summary repo-b [remote] →
context new pin hub_version → amendment hub → resolve stale →
repo-a commit thêm không publish → doctor bắt index lệch exit 1.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aero_kb import gitio, models
from aero_kb.cli import app
from aero_kb.hub import resolve_hub
from aero_kb.query import search

runner = CliRunner()


@pytest.fixture
def fed_world(tmp_path, git_kb, hub_worktree, run_git, monkeypatch):
    """hub bare + repo-a (git_kb, publish 'repo-a') + repo-b (publish 'repo-b')."""
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")  # luôn pull — thấy publish mới nhất
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    # repo-b với 1 doc cục bộ riêng
    repo_b = tmp_path / "repo-b"
    kb_b = repo_b / ".kb"
    doc_dir = kb_b / "roster-sop"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch3.md").write_text(
        "## 3.2 Roster Rules\n\nCrew roster duty limits and rest rules.\n",
        encoding="utf-8",
    )
    (doc_dir / "ch3.raw.md").write_text(
        "## 3.2 Roster Rules\n\nFull text duty limits.\n", encoding="utf-8"
    )
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="roster-sop", title="Roster SOP",
            sections=[models.SectionEntry(
                id="3.2", title="Roster Rules",
                summary="Crew roster duty limits and rest rules.",
                status="reviewed", file="ch3",
            )],
        ),
    )
    models.save_yaml_model(
        kb_b / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id="roster-sop", title="Roster SOP", tags=["crewops"],
            summary="Crew rostering SOP.",
        )]),
    )
    run_git(repo_b, "init")
    run_git(repo_b, "config", "user.name", "test")
    run_git(repo_b, "config", "user.email", "test@test.local")
    run_git(repo_b, "add", "-A")
    run_git(repo_b, "commit", "-m", "repo-b v1")

    from aero_kb.publish import publish

    publish(git_kb["kb"], str(bare), repo_id="repo-a")
    publish(kb_b, str(bare), repo_id="repo-b")
    return {"bare": bare, "repo_a": git_kb, "repo_b": repo_b, "hub_wt": hub_worktree}


def test_query_from_repo_a_sees_hub_and_repo_b(fed_world):
    handle = resolve_hub(str(fed_world["bare"]))
    kb_a = fed_world["repo_a"]["kb"]
    hub_results = search(kb_a, "restrictive airspace designation", hub=handle)
    assert any(r.source == "hub" and r.doc_id == "arinc-424" for r in hub_results)
    remote_results = search(kb_a, "crew roster duty rest", hub=handle)
    remote = [r for r in remote_results if r.source == "remote:repo-b"]
    assert remote
    assert "[remote]" in remote[0].content


def test_context_new_resolve_stale_after_hub_amendment(fed_world, run_git, monkeypatch, tmp_path):
    kb_a = fed_world["repo_a"]["kb"]
    monkeypatch.chdir(fed_world["repo_a"]["root"])
    out = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §5.3",
         "--kb-dir", str(kb_a), "--hub", str(fed_world["bare"])],
    )
    assert out.exit_code == 0, out.output
    block = out.output
    assert "hub_version" in block

    # amendment trên hub → push
    hub_wt = fed_world["hub_wt"]
    l2 = hub_wt / ".kb" / "arinc-424" / "ch5-airspace.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("rest rules", "rest rules")  # no-op guard
        .replace("multiple code, level.", "multiple code, level, NEW field."),
        encoding="utf-8",
    )
    run_git(hub_wt, "add", "-A")
    run_git(hub_wt, "commit", "-m", "amendment")
    run_git(hub_wt, "push", "origin", "HEAD")

    ticket = tmp_path / "ticket.txt"
    ticket.write_text(block, encoding="utf-8")
    res = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(kb_a),
         "--hub", str(fed_world["bare"])],
    )
    assert res.exit_code == 2, res.output  # stale
    assert "status=stale" in res.output
    assert "NEW field" not in res.output  # nội dung trả về là bản pin


def test_doctor_detects_index_out_of_date(fed_world, run_git, monkeypatch):
    root_a = fed_world["repo_a"]["root"]
    kb_a = fed_world["repo_a"]["kb"]
    # commit thêm ở repo-a mà không publish lại
    (root_a / "note.txt").write_text("x", encoding="utf-8")
    run_git(root_a, "add", "-A")
    run_git(root_a, "commit", "-m", "chua publish")
    monkeypatch.chdir(root_a)
    res = runner.invoke(
        app, ["doctor", "--kb-dir", str(kb_a), "--hub", str(fed_world["bare"])]
    )
    # repo_id mặc định = tên git root; git_kb root là tmp dir tên ngẫu nhiên
    # → doctor báo 'chưa publish' (warning) chứ không phải lệch. Kiểm tra lệch
    # bằng check_hub trực tiếp với repo_id='repo-a':
    from aero_kb.doctor import check_hub

    handle = resolve_hub(str(fed_world["bare"]))
    issues, _ = check_hub(kb_a, handle, repo_id="repo-a")
    assert any("lệch" in i.message for i in issues if i.level == "error")


def test_phase2_block_still_resolves(fed_world, monkeypatch, tmp_path):
    """Tiêu chí 5: block Phase 2 (không hub_version) resolve nguyên vẹn."""
    repo_a = fed_world["repo_a"]
    monkeypatch.chdir(repo_a["root"])
    ticket = tmp_path / "old-ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{repo_a["rev1"]}"\n  refs:\n    - demo-doc §1.1\n',
        encoding="utf-8",
    )
    res = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(repo_a["kb"]),
         "--hub", str(fed_world["bare"])],
    )
    assert res.exit_code == 2, res.output  # stale như Phase 2 (amendment rev2)
    assert "status=stale" in res.output
```

- [ ] **Step 2: Chạy E2E**

Run: `python -m pytest tests/test_phase3_e2e.py -v`
Expected: PASS 4/4 — nếu fail, đây là integration bug giữa các task trước; sửa module tương ứng (không sửa test trừ khi test sai).

- [ ] **Step 3: Chạy toàn bộ suite + coverage**

Run: `python -m pytest -q --tb=short`
Expected: PASS toàn bộ. Nếu env có pytest-cov: `python -m pytest --cov=src --cov-report=term-missing -q` — coverage tổng ≥ 80%.

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase3_e2e.py
git commit -m "test: E2E federation — 2 repo + hub, amendment stale, index lệch, block Phase 2 nguyên vẹn"
```

---

### Task 14: Demo script, GitHub Actions mẫu, docs

**Files:**
- Create: `scripts/demo-federation.sh`
- Create: `.github/workflows/kb-publish.yml`
- Create: `docs/deploy-remote-mcp.md`
- Modify: `README.md` (mục 7.9 Phase 3; cập nhật mục 11 giới hạn)

**Interfaces:**
- Consumes: toàn bộ CLI Phase 3 (`publish`, `query --hub`, `context new --hub`, `resolve --hub`, `doctor --hub`).
- Produces: bằng chứng vận hành ≥2 repo (tiêu chí 1) chạy được bằng tay + tài liệu triển khai HTTP MCP (tiêu chí 3) + CI mẫu (tiêu chí 2).

- [ ] **Step 1: Viết `scripts/demo-federation.sh`**

```bash
#!/usr/bin/env bash
# Demo federation Phase 3: hub bare + 2 repo con, chạy trọn vòng.
# Yêu cầu: đã `pip install -e .` và có git. Chạy từ root repo AERO-KB.
set -euo pipefail

WORK=$(mktemp -d)
export AERO_KB_HUB_CACHE="$WORK/cache"
export AERO_KB_HUB_TTL=0
trap 'rm -rf "$WORK"' EXIT
echo "== Demo federation trong $WORK"

git_c() { git -C "$1" -c user.name=demo -c user.email=demo@local "${@:2}"; }

# --- 1. Dựng hub: 1 doc domain + federation/ rỗng ---
HUB="$WORK/kb-hub"
mkdir -p "$HUB/.kb/arinc-424" "$HUB/federation"
cat > "$HUB/.kb/index.yaml" <<'YAML'
docs:
  - id: arinc-424
    title: "ARINC 424"
    revision: "Supplement 22"
    tags: [arinc424, airspace]
    summary: "Navigation database spec."
YAML
cat > "$HUB/.kb/arinc-424/_manifest.yaml" <<'YAML'
id: arinc-424
title: "ARINC 424"
revision: "Supplement 22"
sections:
  - id: "5.3"
    title: "Restrictive Airspace"
    summary: "Restrictive airspace: designation, type, multiple code."
    status: reviewed
    file: ch5-airspace
YAML
printf '## 5.3 Restrictive Airspace\n\nDesignation, type, multiple code, level.\n' \
  > "$HUB/.kb/arinc-424/ch5-airspace.md"
cp "$HUB/.kb/arinc-424/ch5-airspace.md" "$HUB/.kb/arinc-424/ch5-airspace.raw.md"
touch "$HUB/federation/.gitkeep"
git_c "$HUB" init -q && git_c "$HUB" add -A && git_c "$HUB" commit -qm "hub v1"
BARE="$WORK/hub.git"
git init -q --bare "$BARE"
git_c "$HUB" remote add origin "$BARE" && git_c "$HUB" push -q origin HEAD

# --- 2. Dựng 2 repo con demo-nav-data / demo-crew-ops ---
make_repo() { # $1=path $2=doc-id $3=tag $4=summary
  mkdir -p "$1/.kb/$2"
  printf 'docs:\n  - id: %s\n    title: "%s"\n    tags: [%s]\n    summary: "%s"\n' \
    "$2" "$2" "$3" "$4" > "$1/.kb/index.yaml"
  printf 'id: %s\ntitle: "%s"\nsections:\n  - id: "1.1"\n    title: "Overview"\n    summary: "%s"\n    status: reviewed\n    file: ch1\n' \
    "$2" "$2" "$4" > "$1/.kb/$2/_manifest.yaml"
  printf '## 1.1 Overview\n\n%s\n' "$4" > "$1/.kb/$2/ch1.md"
  cp "$1/.kb/$2/ch1.md" "$1/.kb/$2/ch1.raw.md"
  git_c "$1" init -q && git_c "$1" add -A && git_c "$1" commit -qm "v1"
}
make_repo "$WORK/demo-nav-data" nav-mapping navdata "Mapping ARINC records to nav-data services."
make_repo "$WORK/demo-crew-ops" roster-sop crewops "Crew roster duty limits and rest rules."

# --- 3. Publish cả hai lên hub ---
(cd "$WORK/demo-nav-data" && kb publish --hub "$BARE" --repo-id demo-nav-data)
(cd "$WORK/demo-crew-ops" && kb publish --hub "$BARE" --repo-id demo-crew-ops)

# --- 4. Query từ repo A: thấy hub (full L2) + repo B [remote] ---
echo "== Query domain hub từ demo-nav-data:"
(cd "$WORK/demo-nav-data" && kb query "restrictive airspace" --hub "$BARE")
echo "== Query chéo sang demo-crew-ops (chỉ summary [remote]):"
(cd "$WORK/demo-nav-data" && kb query "crew roster duty rest" --hub "$BARE")

# --- 5. context new pin hub_version ---
echo "== Block kb-context cite tài liệu hub:"
BLOCK=$(cd "$WORK/demo-nav-data" && kb context new --refs "arinc-424 §5.3" --hub "$BARE")
echo "$BLOCK"

# --- 6. Amendment hub → resolve báo stale ---
sed -i.bak 's/multiple code, level./multiple code, level, NEW field./' \
  "$HUB/.kb/arinc-424/ch5-airspace.md" && rm -f "$HUB/.kb/arinc-424/ch5-airspace.md.bak"
git_c "$HUB" add -A && git_c "$HUB" commit -qm "amendment" && git_c "$HUB" push -q origin HEAD
echo "== Resolve sau amendment (mong đợi stale, exit 2):"
set +e
(cd "$WORK/demo-nav-data" && echo "$BLOCK" | kb resolve - --hub "$BARE")
echo "exit=$?"
set -e

# --- 7. doctor bắt index lệch ---
(cd "$WORK/demo-nav-data" && touch note.txt && git_c "$WORK/demo-nav-data" add -A \
  && git_c "$WORK/demo-nav-data" commit -qm "chua publish")
echo "== Doctor sau khi repo có commit chưa publish (mong đợi lệch/chưa đồng bộ):"
set +e
(cd "$WORK/demo-nav-data" && kb doctor --hub "$BARE")
echo "exit=$?"
set -e
echo "== Demo xong."
```

Lưu ý: script dùng `kb publish --repo-id` tường minh nên doctor bước 7 báo theo repo-id mặc định (tên thư mục `demo-nav-data` — trùng repo-id đã publish) → thấy đúng lỗi "lệch". `sed -i.bak` để chạy được cả BSD/GNU sed; trên Windows chạy qua Git Bash.

- [ ] **Step 2: Chạy demo script kiểm chứng**

Run: `bash scripts/demo-federation.sh`
Expected: các bước in kết quả như comment; bước 6 in `status=stale` + `exit=2`; bước 7 in `[error] index trên hub lệch...` + `exit=1`.

- [ ] **Step 3: Viết `.github/workflows/kb-publish.yml`**

```yaml
# Mẫu CI publish index lên kb-hub — copy sang các repo con tham gia federation.
# Yêu cầu secret KB_HUB_URL (URL hub kèm token, vd https://x-access-token:${TOKEN}@github.com/org/kb-hub.git)
name: kb-publish
on:
  push:
    branches: [main]
    paths: [".kb/**"]
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install aero-kb  # hoặc pip install -e . nếu repo chứa source
      - name: Publish L0+L1 lên hub
        run: kb publish --hub "${{ secrets.KB_HUB_URL }}" --repo-id "${{ github.event.repository.name }}"
        env:
          GIT_AUTHOR_NAME: kb-publish-ci
          GIT_AUTHOR_EMAIL: ci@local
          GIT_COMMITTER_NAME: kb-publish-ci
          GIT_COMMITTER_EMAIL: ci@local
```

- [ ] **Step 4: Viết `docs/deploy-remote-mcp.md`**

```markdown
# Triển khai Remote HTTP MCP cho BA (Phase 3)

Mục tiêu: BA truy vấn KB qua MCP không cần clone repo (spec Phase 3 §10).

## Máy chủ nội bộ

1. Clone hub: `git clone <kb-hub-url> /srv/kb-hub`
2. Cài tool: `pip install aero-kb` (thêm `.[embed]` nếu muốn semantic search)
3. Đặt token: `export AERO_KB_HTTP_TOKEN=$(openssl rand -hex 24)` — lưu vào secret manager
4. Chạy server:
   `python -m aero_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321`
5. Cron giữ hub tươi (mỗi 5 phút): `*/5 * * * * git -C /srv/kb-hub pull --ff-only`

### systemd unit mẫu

    [Unit]
    Description=AERO-KB remote MCP
    After=network.target

    [Service]
    Environment=AERO_KB_HTTP_TOKEN=<token>
    ExecStart=/usr/bin/python3 -m aero_kb.mcp --kb /srv/kb-hub/.kb --hub /srv/kb-hub --transport http --host 0.0.0.0 --port 8321
    Restart=on-failure

    [Install]
    WantedBy=multi-user.target

## Cấu hình client (Claude Code / Cowork)

    {
      "mcpServers": {
        "aero-kb": {
          "type": "http",
          "url": "http://kb.internal:8321/mcp",
          "headers": { "Authorization": "Bearer <token>" }
        }
      }
    }

Lưu ý: chỉ chạy trong mạng nội bộ/VPN — tài liệu có bản quyền. Server từ chối
khởi động nếu thiếu `AERO_KB_HTTP_TOKEN`.
```

- [ ] **Step 5: Cập nhật `README.md`**

- Mục 7 (bảng lệnh): thêm dòng `kb publish` và cờ `--hub`/`--semantic` của `query`.
- Thêm mục `7.9 Phase 3 — Federation & remote MCP`: tóm tắt hub là gì, 3 lệnh/flag mới (`publish`, `--hub`, `--semantic`), block `kb-context` nay có thể kèm `hub_version`, link `docs/deploy-remote-mcp.md` và `scripts/demo-federation.sh`. Văn phong không-kỹ-thuật như phần còn lại của README.
- Mục 11 (giới hạn): bỏ dòng "Chưa có kb-hub tập trung..." và dòng "Chưa hỗ trợ embedding search"; giữ/ghi rõ mục còn lại: codebase extraction (deferred), summarize chưa chạy nền, ~2,4% section lỗi trích xuất.
- Cây thư mục mục 5: thêm `scripts/` và `docs/deploy-remote-mcp.md`.

- [ ] **Step 6: Chạy toàn bộ test lần cuối**

Run: `python -m pytest -q`
Expected: PASS toàn bộ

- [ ] **Step 7: Commit**

```bash
git add scripts/demo-federation.sh .github/workflows/kb-publish.yml docs/deploy-remote-mcp.md README.md
git commit -m "docs: demo federation, CI publish mẫu, hướng dẫn remote MCP, README Phase 3"
```

---

## Nghiệm thu cuối (đối chiếu tiêu chí spec §1)

1. **≥2 repo federation** — `tests/test_phase3_e2e.py` + `scripts/demo-federation.sh` (Task 13, 14).
2. **doctor bắt index lệch + hub stale** — Task 9 + E2E Task 13.
3. **BA qua HTTP MCP với bearer token** — Task 10 + `docs/deploy-remote-mcp.md`.
4. **Embedding là bước 3 routing, fallback an toàn** — Task 11, 12.
5. **Block Phase 2 nguyên vẹn** — `test_phase2_block_still_resolves` (Task 13) + suite Phase 2 chạy lại ở mọi task.
