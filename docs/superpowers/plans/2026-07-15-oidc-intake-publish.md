# OIDC Intake Publish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repo con đóng góp tri thức lên hub qua PR mà không giữ secret ghi hub nào — CI child xác thực bằng OIDC JWT, service intake (mở rộng HTTP server hiện có) verify + cầm GitHub App token + mở PR; đồng thời publish trở thành incremental (hash-manifest, chi phí ∝ thay đổi, no-op khi không đổi).

**Architecture:** Thêm 4 module mới (`hashsync`, `ghapp`, `intake`, `cipublish`) + route `/intake/*` gắn vào ASGI app hiện có (`web/app.py`). `publish._snapshot` chuyển từ `rmtree+copytree` sang hash-diff sync. CLI `kb publish` thêm intake mode (tag `kb-publish/<ts>` + poll status); CLI `kb ci-publish` chạy trong GitHub Actions của child.

**Tech Stack:** Python 3.11+, Starlette, PyJWT[crypto] (verify RS256 + mint App JWT), python-multipart (form upload), urllib stdlib (HTTP client), pytest.

**Spec:** `docs/superpowers/specs/2026-07-15-oidc-intake-publish-design.md`

## Global Constraints

- Python floor: `requires-python >= 3.11` — không dùng API mới hơn (không dùng `tarfile filter=` — extract thủ công).
- Dependency mới chỉ trong optional extras: `server = ["PyJWT[crypto]>=2.8", "python-multipart>=0.0.9"]`; extra `dev` thêm 2 package đó để test.
- Hermetic tests: không network thật, không GitHub thật, không `gh` thật. JWT ký bằng RSA key sinh trong test; GitHub API fake bằng callable inject.
- Không bao giờ log OIDC token hay installation token; scrub credentialed URL khỏi error message.
- Mọi path ghi/xóa trên hub qua guard `is_relative_to`.
- Tất cả file mới có `from __future__ import annotations`; type hints đầy đủ; theo style repo (subprocess wrapper pattern của `gitio.py`, error class per module).
- Coverage ≥80%; chạy test bằng `python -m pytest` từ repo root (venv: `.venv` nếu có).
- Commit format: `<type>: <description>` (feat/fix/test/docs/chore), không attribution.

---

### Task 1: `hashsync.py` — manifest, diff, apply

**Files:**
- Create: `src/center_kb/hashsync.py`
- Test: `tests/test_hashsync.py`

**Interfaces:**
- Produces:
  - `build_manifest(root: Path, exclude: tuple[str, ...] = ()) -> dict[str, str]` — `{posix-relpath → sha256-hex}` của mọi regular file dưới `root` (bỏ symlink), key sort tăng dần; `root` không tồn tại → `{}`.
  - `diff_manifests(local: dict[str, str], remote: dict[str, str]) -> tuple[list[str], list[str]]` — `(changed, deleted)`, cả hai sorted. `changed` = path có ở local mà hash khác/thiếu ở remote; `deleted` = path có ở remote mà vắng ở local.
  - `apply_sync(src_root: Path, dest_root: Path, changed: list[str], deleted: list[str]) -> None` — copy từng file changed, unlink từng file deleted (chmod +w retry cho Windows read-only), prune thư mục rỗng. Path escape khỏi `dest_root` → raise `HashSyncError`.
  - `class HashSyncError(RuntimeError)`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_hashsync.py
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from center_kb import hashsync


def _write(root: Path, rel: str, content: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestBuildManifest:
    def test_maps_relpath_to_sha256_sorted(self, tmp_path):
        _write(tmp_path, "b/two.md", "two")
        _write(tmp_path, "a/one.md", "one")
        man = hashsync.build_manifest(tmp_path)
        assert list(man) == ["a/one.md", "b/two.md"]
        # sha256("one") — giá trị cố định, manifest phải deterministic
        assert man["a/one.md"] == (
            "7692c3ad3540bb803c020b3aee66cd8887123234ea0c6e7143c0add73ff431ed"
        )

    def test_missing_root_returns_empty(self, tmp_path):
        assert hashsync.build_manifest(tmp_path / "nope") == {}

    def test_exclude_skips_exact_relpath(self, tmp_path):
        _write(tmp_path, "_meta.yaml", "x")
        _write(tmp_path, "doc/index.yaml", "y")
        man = hashsync.build_manifest(tmp_path, exclude=("_meta.yaml",))
        assert "_meta.yaml" not in man
        assert "doc/index.yaml" in man

    def test_hash_is_bytes_exact_crlf_differs(self, tmp_path):
        (tmp_path / "f.md").write_bytes(b"line\r\n")
        man1 = hashsync.build_manifest(tmp_path)
        (tmp_path / "f.md").write_bytes(b"line\n")
        man2 = hashsync.build_manifest(tmp_path)
        assert man1["f.md"] != man2["f.md"]


class TestDiffManifests:
    def test_changed_new_deleted_and_empty(self):
        local = {"a": "1", "b": "2-new", "c": "3"}
        remote = {"a": "1", "b": "2-old", "d": "4"}
        changed, deleted = hashsync.diff_manifests(local, remote)
        assert changed == ["b", "c"]
        assert deleted == ["d"]
        assert hashsync.diff_manifests({"a": "1"}, {"a": "1"}) == ([], [])


class TestApplySync:
    def test_copies_deletes_and_prunes_empty_dirs(self, tmp_path):
        src, dest = tmp_path / "src", tmp_path / "dest"
        _write(src, "keep/new.md", "new")
        _write(dest, "old/gone.md", "bye")
        hashsync.apply_sync(src, dest, ["keep/new.md"], ["old/gone.md"])
        assert (dest / "keep/new.md").read_text(encoding="utf-8") == "new"
        assert not (dest / "old/gone.md").exists()
        assert not (dest / "old").exists()  # pruned

    def test_deletes_readonly_file(self, tmp_path):
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir()
        target = _write(dest, "ro.md", "x")
        os.chmod(target, stat.S_IREAD)
        hashsync.apply_sync(src, dest, [], ["ro.md"])
        assert not target.exists()

    @pytest.mark.parametrize("bad", ["../escape.md", "a/../../up.md"])
    def test_path_escape_raises(self, tmp_path, bad):
        src, dest = tmp_path / "src", tmp_path / "dest"
        src.mkdir(), dest.mkdir()
        with pytest.raises(hashsync.HashSyncError):
            hashsync.apply_sync(src, dest, [], [bad])
        with pytest.raises(hashsync.HashSyncError):
            hashsync.apply_sync(src, dest, [bad], [])
```

- [ ] **Step 2: Run tests, verify FAIL**

Run: `python -m pytest tests/test_hashsync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.hashsync'`

- [ ] **Step 3: Implement**

```python
# src/center_kb/hashsync.py
from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path


class HashSyncError(RuntimeError):
    """A sync path escapes the destination root."""


def build_manifest(root: Path, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    """{posix relpath → sha256 hex} of every regular file under root, keys sorted.

    Hashes raw bytes (no newline normalization) — deterministic per content.
    Symlinks are skipped: federation snapshots hold regular files only.
    """
    if not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel in exclude:
            continue
        h = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[rel] = h.hexdigest()
    return out


def diff_manifests(
    local: dict[str, str], remote: dict[str, str]
) -> tuple[list[str], list[str]]:
    changed = sorted(p for p, h in local.items() if remote.get(p) != h)
    deleted = sorted(p for p in remote if p not in local)
    return changed, deleted


def _guard(dest_root: Path, rel: str) -> Path:
    target = (dest_root / rel).resolve()
    if not target.is_relative_to(dest_root.resolve()):
        raise HashSyncError(f"path '{rel}' escapes '{dest_root}' — refusing")
    return target


def _unlink_force(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IWRITE)
        path.unlink()


def apply_sync(
    src_root: Path, dest_root: Path, changed: list[str], deleted: list[str]
) -> None:
    dest_root.mkdir(parents=True, exist_ok=True)
    for rel in changed:
        target = _guard(dest_root, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _unlink_force(target)  # Windows: copy2 onto read-only fails
        shutil.copy2(src_root / rel, target)
    for rel in deleted:
        target = _guard(dest_root, rel)
        if target.exists():
            _unlink_force(target)
    for d in sorted((p for p in dest_root.rglob("*") if p.is_dir()), reverse=True):
        try:
            d.rmdir()  # only succeeds when empty
        except OSError:
            pass
```

- [ ] **Step 4: Run tests, verify PASS**

Run: `python -m pytest tests/test_hashsync.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/hashsync.py tests/test_hashsync.py
git commit -m "feat: hashsync — content-hash manifest, diff, targeted sync"
```

---

### Task 2: `publish._snapshot` incremental + no-op

**Files:**
- Modify: `src/center_kb/publish.py` (hàm `_snapshot`, `_publish_direct`, `_publish_pr`; xóa `_rmtree_force`)
- Modify: `tests/test_publish_rmtree.py` (xóa — thay bằng test read-only trong test_hashsync đã có)
- Test: `tests/test_publish.py` (thêm test no-op; sửa nếu có test gọi `_snapshot` trực tiếp)

**Interfaces:**
- Consumes: `hashsync.build_manifest/diff_manifests/apply_sync` (Task 1).
- Produces: `_snapshot(kb_abs: Path, handle: HubHandle, rid: str, source_commit: str, source_url: str | None = None) -> tuple[int, bool]` — `(n_docs, changed)`. `changed=False` → không ghi gì (kể cả `_meta.yaml`). `source_url=None` → lấy từ git remote của `kb_abs` (hành vi cũ); intake (Task 7) truyền tường minh.

- [ ] **Step 1: Write failing tests** — thêm vào `tests/test_publish.py`:

```python
def test_publish_twice_no_change_is_noop(tmp_path, child_repo, hub_path):
    """Lần 2 không đổi gì: không commit mới, _meta.yaml giữ nguyên."""
    from center_kb import publish as publish_mod

    publish_mod.publish(child_repo / ".kb", str(hub_path), repo_id="child-a")
    meta_path = hub_path / "federation" / "child-a" / "_meta.yaml"
    meta_before = meta_path.read_text(encoding="utf-8")
    log_before = subprocess.run(
        ["git", "log", "--oneline"], cwd=hub_path,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout

    report = publish_mod.publish(child_repo / ".kb", str(hub_path), repo_id="child-a")

    assert meta_path.read_text(encoding="utf-8") == meta_before
    log_after = subprocess.run(
        ["git", "log", "--oneline"], cwd=hub_path,
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    assert log_after == log_before
    assert report.n_docs >= 0  # report vẫn trả về bình thường


def test_publish_removed_file_deleted_on_hub(tmp_path, child_repo, hub_path):
    from center_kb import publish as publish_mod

    extra = child_repo / ".kb" / "stray.md"
    extra.write_text("temp", encoding="utf-8")
    publish_mod.publish(child_repo / ".kb", str(hub_path), repo_id="child-a")
    assert (hub_path / "federation" / "child-a" / "stray.md").exists()

    extra.unlink()
    publish_mod.publish(child_repo / ".kb", str(hub_path), repo_id="child-a")
    assert not (hub_path / "federation" / "child-a" / "stray.md").exists()
```

Lưu ý: dùng đúng tên fixture sẵn có của `tests/test_publish.py` (mở file, xem fixture tạo child repo + hub local-path — nếu tên khác `child_repo`/`hub_path` thì đổi theo; nếu chưa có fixture tái dùng được, chép cách dựng repo tmp từ test publish đầu tiên trong file).

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_publish.py -v -k "noop or removed_file"`
Expected: FAIL — `_meta.yaml` đổi (published_at mới) và/hoặc có commit mới ở lần publish 2.

- [ ] **Step 3: Implement** — trong `src/center_kb/publish.py`:

Thay toàn bộ `_rmtree_force` + `_snapshot` bằng:

```python
def _snapshot(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
) -> tuple[int, bool]:
    """Sync .kb/ → federation/<rid>/ theo hash-diff; trả (n_docs, changed).

    changed=False: nội dung y hệt snapshot trên hub — không ghi gì, kể cả
    _meta.yaml (published_at chỉ đổi khi nội dung thực sự đổi → publish
    lần 2 liên tiếp là no-op đúng nghĩa, không commit, không PR).
    """
    from center_kb import hashsync

    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    local_man = hashsync.build_manifest(kb_abs)
    dest_man = hashsync.build_manifest(dest, exclude=("_meta.yaml",))
    changed, deleted = hashsync.diff_manifests(local_man, dest_man)
    if not changed and not deleted:
        return len(local_index.docs), False
    hashsync.apply_sync(kb_abs, dest, changed, deleted)
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=(
            source_url
            if source_url is not None
            else gitio.remote_url(gitio.git_root(kb_abs))
        ),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    return len(local_index.docs), True
```

Xóa import `shutil`, `stat`, `sys` nếu không còn dùng. Cập nhật 2 caller:

Trong `_publish_direct` — dòng `n_docs = _snapshot(...)` thành:

```python
    n_docs, changed = _snapshot(kb_abs, handle, rid, source_commit)
```

(giữ nguyên phần sau — `commit_paths` tự trả False khi tree sạch).

Trong `_publish_pr` — dòng `n_docs = _snapshot(...)` thành:

```python
        n_docs, changed = _snapshot(kb_abs, handle, rid, source_commit)
```

Xóa file `tests/test_publish_rmtree.py` (hành vi read-only giờ thuộc `hashsync._unlink_force`, đã test ở Task 1).

- [ ] **Step 4: Run full publish suite, verify PASS**

Run: `python -m pytest tests/test_publish.py tests/test_cli_hub.py -v`
Expected: PASS toàn bộ. Nếu test cũ nào assert hành vi rmtree/copytree hoặc unpack `_snapshot` trả 1 giá trị → sửa theo signature mới `(n_docs, changed)`.

- [ ] **Step 5: Commit**

```bash
git add -A src/center_kb/publish.py tests/
git commit -m "feat: incremental publish — hash-diff sync, true no-op when unchanged"
```

---

### Task 3: Registry model + loader

**Files:**
- Modify: `src/center_kb/models.py`
- Modify: `src/center_kb/federation.py`
- Test: `tests/test_federation_registry.py`

**Interfaces:**
- Produces:
  - `models.Registry(BaseModel)` — field `repos: dict[str, str]` (`"owner/repo" → repo_id`).
  - `federation.REGISTRY_NAME = "registry.yaml"`, `federation.RegistryError(RuntimeError)`.
  - `federation.load_registry(federation_dir: Path) -> models.Registry` — file thiếu → Registry rỗng; YAML/schema hỏng → raise `RegistryError` (fail đóng).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_federation_registry.py
from __future__ import annotations

import pytest

from center_kb import federation, models


def test_missing_file_returns_empty(tmp_path):
    reg = federation.load_registry(tmp_path)
    assert reg.repos == {}


def test_loads_mapping(tmp_path):
    (tmp_path / "registry.yaml").write_text(
        "repos:\n  acme/flight-docs: flight-docs\n", encoding="utf-8"
    )
    reg = federation.load_registry(tmp_path)
    assert reg.repos["acme/flight-docs"] == "flight-docs"


@pytest.mark.parametrize("bad", ["repos: [broken", "repos: 42"])
def test_invalid_yaml_or_schema_raises(tmp_path, bad):
    (tmp_path / "registry.yaml").write_text(bad, encoding="utf-8")
    with pytest.raises(federation.RegistryError):
        federation.load_registry(tmp_path)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_federation_registry.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.federation' has no attribute 'load_registry'`

- [ ] **Step 3: Implement**

`models.py` — thêm sau `FederationIndex`:

```python
class Registry(BaseModel):
    """federation/registry.yaml — allowlist: GitHub 'owner/repo' → repo_id on the hub."""

    repos: dict[str, str] = Field(default_factory=dict)
```

`federation.py` — thêm sau `FEDERATION_INDEX_NAME`:

```python
REGISTRY_NAME = "registry.yaml"


class RegistryError(RuntimeError):
    """federation/registry.yaml is unreadable — intake must fail closed."""


def load_registry(federation_dir: Path) -> models.Registry:
    path = federation_dir / REGISTRY_NAME
    if not path.exists():
        return models.Registry()
    try:
        return models.load_yaml_model(path, models.Registry)
    except (yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"federation/{REGISTRY_NAME} is invalid: {exc}") from exc
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_federation_registry.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/models.py src/center_kb/federation.py tests/test_federation_registry.py
git commit -m "feat: federation registry — owner/repo → repo_id allowlist"
```

---

### Task 4: `gitio` — tag, push tag, push branch tới URL một-lần

**Files:**
- Modify: `src/center_kb/gitio.py`
- Test: `tests/test_gitio_tags.py`

**Interfaces:**
- Produces:
  - `gitio.tag(root: Path, name: str) -> None` — `git tag <name>`; fail → `GitError`.
  - `gitio.push_tag(root: Path, name: str) -> None` — `git push origin refs/tags/<name>`.
  - `gitio.push_branch_url(root: Path, url: str, branch: str) -> None` — `git push --force <url> <branch>:<branch>`; error message **scrub `url`** (chứa token).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_gitio_tags.py
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from center_kb import gitio


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


@pytest.fixture
def remote(tmp_path, repo):
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--bare", str(repo), str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    return bare


def test_tag_and_push_tag(repo, remote):
    gitio.tag(repo, "kb-publish/20260715-000000")
    gitio.push_tag(repo, "kb-publish/20260715-000000")
    out = _git(remote, "tag", "--list")
    assert "kb-publish/20260715-000000" in out


def test_tag_duplicate_raises(repo):
    gitio.tag(repo, "dup")
    with pytest.raises(gitio.GitError):
        gitio.tag(repo, "dup")


def test_push_branch_url_force_pushes(repo, remote):
    _git(repo, "checkout", "-b", "publish/x")
    (repo / "f.txt").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "c2")
    gitio.push_branch_url(repo, str(remote), "publish/x")
    assert "publish/x" in _git(remote, "branch", "--list", "--all")


def test_push_branch_url_scrubs_url_from_error(repo, tmp_path):
    secret_url = f"{tmp_path / 'missing.git'}"
    with pytest.raises(gitio.GitError) as exc:
        gitio.push_branch_url(repo, secret_url, "main")
    assert secret_url not in str(exc.value)
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_gitio_tags.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.gitio' has no attribute 'tag'`

- [ ] **Step 3: Implement** — thêm cuối `gitio.py`:

```python
def tag(root: Path, name: str) -> None:
    proc = _run(root, "tag", name)
    if proc.returncode != 0:
        raise GitError(f"tag '{name}' failed: {proc.stderr.strip()}")


def push_tag(root: Path, name: str) -> None:
    proc = _run(root, "push", "origin", f"refs/tags/{name}")
    if proc.returncode != 0:
        raise GitError(f"push tag '{name}' failed: {proc.stderr.strip()}")


def push_branch_url(root: Path, url: str, branch: str) -> None:
    """Force-push `branch` to an explicit remote URL.

    The URL may embed a short-lived credential (x-access-token) — it is
    scrubbed from any error message so tokens never reach logs.
    """
    proc = _run(root, "push", "--force", url, f"{branch}:{branch}")
    if proc.returncode != 0:
        detail = proc.stderr.strip().replace(url, "<hub-url>")
        raise GitError(f"push branch '{branch}' failed: {detail}")
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_gitio_tags.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/gitio.py tests/test_gitio_tags.py
git commit -m "feat: gitio tag/push_tag/push_branch_url (credential-scrubbed)"
```

---

### Task 5: deps + `ghapp.py` — GitHub App token & PR qua REST

**Files:**
- Modify: `pyproject.toml`
- Create: `src/center_kb/ghapp.py`
- Test: `tests/test_ghapp.py`

**Interfaces:**
- Produces:
  - `ghapp.GHAppError(RuntimeError)`
  - `ghapp.AppCreds` — dataclass `{app_id: str, private_key_pem: str}`
  - `ghapp.repo_full_from_url(url: str) -> str` — `https://github.com/o/r.git` | `git@github.com:o/r.git` → `"o/r"`; không phải GitHub → `GHAppError`.
  - `ghapp.mint_installation_token(creds: AppCreds, repo_full: str, http=_default_http) -> str`
  - `ghapp.create_or_get_pr(repo_full: str, token: str, head_branch: str, title: str, body: str, base: str = "main", http=_default_http) -> str` — trả PR html_url; 422 (đã có PR) → GET PR đang mở của head đó.
  - `http` seam: `Callable[[urllib.request.Request], tuple[int, bytes]]`.
- Consumes: PyJWT (`jwt.encode` RS256) — dependency mới.

- [ ] **Step 1: Add deps** — `pyproject.toml`:

```toml
[project.optional-dependencies]
ingest = ["docling>=2.0"]
dev = [
    "pytest>=8.0", "anyio>=4.0", "sqlite-vec>=0.1.6", "twine>=5.0", "build>=1.2",
    "PyJWT[crypto]>=2.8", "python-multipart>=0.0.9", "httpx>=0.27",
]
embed = ["sqlite-vec>=0.1.6", "fastembed>=0.3"]
server = ["PyJWT[crypto]>=2.8", "python-multipart>=0.0.9"]
```

(`httpx` cho Starlette TestClient — kiểm tra: nếu `tests/test_web_api.py` đang chạy được nghĩa là httpx đã có mặt gián tiếp, vẫn khai báo tường minh.)

Run: `pip install -e ".[dev,embed]"`
Expected: cài PyJWT + cryptography + python-multipart thành công.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_ghapp.py
from __future__ import annotations

import json

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from center_kb import ghapp


@pytest.fixture(scope="module")
def rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class FakeHTTP:
    """Ghi lại request; trả response theo hàng đợi [(status, dict), ...]."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/acme/kb-hub.git", "acme/kb-hub"),
        ("https://github.com/acme/kb-hub", "acme/kb-hub"),
        ("git@github.com:acme/kb-hub.git", "acme/kb-hub"),
    ],
)
def test_repo_full_from_url(url, expected):
    assert ghapp.repo_full_from_url(url) == expected


def test_repo_full_from_url_rejects_non_github():
    with pytest.raises(ghapp.GHAppError):
        ghapp.repo_full_from_url("https://gitlab.com/a/b.git")


def test_mint_installation_token(rsa_pem):
    http = FakeHTTP([(200, {"id": 77}), (201, {"token": "ghs_test"})])
    creds = ghapp.AppCreds(app_id="1234", private_key_pem=rsa_pem)
    token = ghapp.mint_installation_token(creds, "acme/kb-hub", http=http)
    assert token == "ghs_test"
    # request 1: GET installation; request 2: POST access_tokens — mang app JWT
    assert "/repos/acme/kb-hub/installation" in http.requests[0].full_url
    assert "/app/installations/77/access_tokens" in http.requests[1].full_url
    auth = http.requests[0].headers["Authorization"]
    claims = pyjwt.decode(
        auth.removeprefix("Bearer "), options={"verify_signature": False}
    )
    assert claims["iss"] == "1234"


def test_create_pr_created(rsa_pem):
    http = FakeHTTP([(201, {"html_url": "https://github.com/acme/kb-hub/pull/5"})])
    url = ghapp.create_or_get_pr(
        "acme/kb-hub", "ghs_x", "publish/child-a", "t", "b", base="main", http=http
    )
    assert url.endswith("/pull/5")
    sent = json.loads(http.requests[0].data)
    assert sent == {"title": "t", "body": "b", "head": "publish/child-a", "base": "main"}


def test_create_pr_already_exists_returns_open_pr(rsa_pem):
    http = FakeHTTP(
        [
            (422, {"message": "already exists"}),
            (200, [{"html_url": "https://github.com/acme/kb-hub/pull/3"}]),
        ]
    )
    url = ghapp.create_or_get_pr(
        "acme/kb-hub", "ghs_x", "publish/child-a", "t", "b", http=http
    )
    assert url.endswith("/pull/3")


def test_http_error_raises_without_token_in_message():
    http = FakeHTTP([(500, {"message": "boom"})])
    with pytest.raises(ghapp.GHAppError) as exc:
        ghapp.create_or_get_pr("acme/kb-hub", "ghs_secret", "b", "t", "b", http=http)
    assert "ghs_secret" not in str(exc.value)
```

- [ ] **Step 3: Run, verify FAIL**

Run: `python -m pytest tests/test_ghapp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.ghapp'`

- [ ] **Step 4: Implement**

```python
# src/center_kb/ghapp.py
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com"
_GH_URL_RE = re.compile(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$")


class GHAppError(RuntimeError):
    """GitHub App call failed (token is never included in the message)."""


@dataclass
class AppCreds:
    app_id: str
    private_key_pem: str


def _default_http(req: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def repo_full_from_url(url: str) -> str:
    m = _GH_URL_RE.search(url)
    if not m:
        raise GHAppError(f"'{url}' is not a GitHub repo URL")
    return m.group(1)


def _app_jwt(creds: AppCreds) -> str:
    import jwt

    now = int(time.time())
    return jwt.encode(
        {"iat": now - 60, "exp": now + 540, "iss": creds.app_id},
        creds.private_key_pem,
        algorithm="RS256",
    )


def _call(
    method: str, url: str, bearer: str, body: dict | None, http
) -> tuple[int, dict | list]:
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    status, raw = http(req)
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {}
    return status, data


def mint_installation_token(
    creds: AppCreds, repo_full: str, http=_default_http
) -> str:
    app_jwt = _app_jwt(creds)
    status, inst = _call(
        "GET", f"{API}/repos/{repo_full}/installation", app_jwt, None, http
    )
    if status != 200:
        raise GHAppError(
            f"GET installation for '{repo_full}' → {status} — "
            "is the GitHub App installed on the hub repo?"
        )
    status, tok = _call(
        "POST",
        f"{API}/app/installations/{inst['id']}/access_tokens",
        app_jwt,
        {},
        http,
    )
    if status != 201:
        raise GHAppError(f"mint installation token → {status}")
    return tok["token"]


def create_or_get_pr(
    repo_full: str,
    token: str,
    head_branch: str,
    title: str,
    body: str,
    base: str = "main",
    http=_default_http,
) -> str:
    status, data = _call(
        "POST",
        f"{API}/repos/{repo_full}/pulls",
        token,
        {"title": title, "body": body, "head": head_branch, "base": base},
        http,
    )
    if status == 201:
        return data["html_url"]
    if status == 422:  # PR for this head already open — fetch it
        owner = repo_full.split("/")[0]
        status2, prs = _call(
            "GET",
            f"{API}/repos/{repo_full}/pulls?head={owner}:{head_branch}&state=open",
            token,
            None,
            http,
        )
        if status2 == 200 and isinstance(prs, list) and prs:
            return prs[0]["html_url"]
    raise GHAppError(f"create PR on '{repo_full}' → {status}")
```

- [ ] **Step 5: Run, verify PASS**

Run: `python -m pytest tests/test_ghapp.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/center_kb/ghapp.py tests/test_ghapp.py
git commit -m "feat: ghapp — GitHub App installation token + PR via REST, [server] extra"
```

---

### Task 6: `intake.py` — OIDC verify, authorize, safe-extract, status store

**Files:**
- Create: `src/center_kb/intake.py`
- Test: `tests/test_intake_core.py`

**Interfaces:**
- Produces:
  - `intake.GITHUB_ISSUER = "https://token.actions.githubusercontent.com"`; `intake.TAG_REF_PREFIX = "refs/tags/kb-publish/"`; `intake.DEFAULT_MAX_TAR = 50 * 1024 * 1024`
  - `intake.IntakeError(RuntimeError)` — attr `status: int`, `detail: str`
  - `intake.verify_oidc(token: str, audience: str, key_resolver=None) -> dict` — claims; lỗi nào cũng → `IntakeError(401)`. `key_resolver: Callable[[str], Any]` (token → public key); mặc định PyJWKClient cached.
  - `intake.authorize(claims: dict, registry: models.Registry) -> str` — trả `repo_id`; ref sai / repo lạ → `IntakeError(403)`; repo_id trong registry không khớp `publish._REPO_ID_RE` → `IntakeError(500)`.
  - `intake.safe_extract(data: bytes, dest: Path, max_bytes: int = DEFAULT_MAX_TAR) -> None` — chỉ regular file; traversal/absolute/symlink → `IntakeError(400)`; oversize → `IntakeError(413)`.
  - `intake.StatusStore(path: Path | None)` — `.set(repo_id, commit, state, pr_url="", detail="")`, `.get(repo_id, commit) -> dict | None`; thread-safe; persist JSON nếu có path.
  - `intake.repo_lock(repo_id: str) -> threading.Lock`
- Consumes: `models.Registry` (Task 3), `publish._REPO_ID_RE` (sẵn có).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_intake_core.py
from __future__ import annotations

import io
import tarfile
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from center_kb import intake, models

AUD = "https://kb.internal:8321"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


def _token(pem, pub, **overrides):
    now = int(time.time())
    claims = {
        "iss": intake.GITHUB_ISSUER,
        "aud": AUD,
        "iat": now,
        "exp": now + 300,
        "repository": "acme/flight-docs",
        "ref": "refs/tags/kb-publish/20260715-010101",
    }
    claims.update(overrides)
    return pyjwt.encode(claims, pem, algorithm="RS256")


class TestVerifyOIDC:
    def test_valid_token_returns_claims(self, keypair):
        pem, pub = keypair
        claims = intake.verify_oidc(_token(pem, pub), AUD, key_resolver=lambda t: pub)
        assert claims["repository"] == "acme/flight-docs"

    @pytest.mark.parametrize(
        "override",
        [
            {"aud": "https://other"},
            {"iss": "https://evil.example"},
            {"exp": int(time.time()) - 10},
        ],
    )
    def test_bad_claims_rejected_401(self, keypair, override):
        pem, pub = keypair
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, pub, **override), AUD, key_resolver=lambda t: pub
            )
        assert exc.value.status == 401

    def test_wrong_signature_rejected(self, keypair):
        pem, _ = keypair
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        with pytest.raises(intake.IntakeError) as exc:
            intake.verify_oidc(
                _token(pem, None), AUD, key_resolver=lambda t: other.public_key()
            )
        assert exc.value.status == 401


class TestAuthorize:
    REG = models.Registry(repos={"acme/flight-docs": "flight-docs"})

    def test_known_repo_returns_rid(self):
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        assert intake.authorize(claims, self.REG) == "flight-docs"

    def test_unknown_repo_403_with_registry_hint(self):
        claims = {"repository": "evil/repo", "ref": "refs/tags/kb-publish/x"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403
        assert "registry.yaml" in exc.value.detail

    def test_non_publish_ref_403(self):
        claims = {"repository": "acme/flight-docs", "ref": "refs/heads/main"}
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, self.REG)
        assert exc.value.status == 403

    def test_registry_rid_with_path_separator_500(self):
        reg = models.Registry(repos={"acme/flight-docs": "../evil"})
        claims = {
            "repository": "acme/flight-docs",
            "ref": "refs/tags/kb-publish/x",
        }
        with pytest.raises(intake.IntakeError) as exc:
            intake.authorize(claims, reg)
        assert exc.value.status == 500


def _tar_bytes(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class TestSafeExtract:
    def test_extracts_regular_files(self, tmp_path):
        data = _tar_bytes({"index.yaml": b"docs: []", "d/s.md": b"hi"})
        intake.safe_extract(data, tmp_path)
        assert (tmp_path / "index.yaml").read_bytes() == b"docs: []"
        assert (tmp_path / "d" / "s.md").read_bytes() == b"hi"

    @pytest.mark.parametrize("name", ["../up.md", "/abs.md", "a/../../out.md"])
    def test_traversal_rejected_400(self, tmp_path, name):
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(_tar_bytes({name: b"x"}), tmp_path)
        assert exc.value.status == 400

    def test_symlink_rejected_400(self, tmp_path):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            info = tarfile.TarInfo("link.md")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(buf.getvalue(), tmp_path)
        assert exc.value.status == 400

    def test_oversize_rejected_413(self, tmp_path):
        data = _tar_bytes({"big.md": b"x" * 2048})
        with pytest.raises(intake.IntakeError) as exc:
            intake.safe_extract(data, tmp_path, max_bytes=100)
        assert exc.value.status == 413


class TestStatusStore:
    def test_set_get_roundtrip_and_persistence(self, tmp_path):
        path = tmp_path / "status.json"
        store = intake.StatusStore(path)
        store.set("flight-docs", "abc1234", "done", pr_url="https://x/pull/1")
        got = store.get("flight-docs", "abc1234")
        assert got == {"state": "done", "pr_url": "https://x/pull/1", "detail": ""}
        # reload từ file
        store2 = intake.StatusStore(path)
        assert store2.get("flight-docs", "abc1234")["state"] == "done"

    def test_unknown_returns_none(self, tmp_path):
        store = intake.StatusStore(None)
        assert store.get("x", "y") is None


def test_repo_lock_same_id_same_lock():
    assert intake.repo_lock("a") is intake.repo_lock("a")
    assert intake.repo_lock("a") is not intake.repo_lock("b")
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_intake_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.intake'`

- [ ] **Step 3: Implement**

```python
# src/center_kb/intake.py
from __future__ import annotations

import io
import json
import logging
import tarfile
import threading
from pathlib import Path

from center_kb import models

logger = logging.getLogger("center_kb.intake")

GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
JWKS_URL = GITHUB_ISSUER + "/.well-known/jwks"
TAG_REF_PREFIX = "refs/tags/kb-publish/"
DEFAULT_MAX_TAR = 50 * 1024 * 1024


class IntakeError(RuntimeError):
    """Publish intake rejected the request; maps to an HTTP status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_jwks_client = None
_jwks_lock = threading.Lock()


def _default_key_resolver(token: str):
    """PyJWKClient resolves + caches GitHub's signing keys by `kid`."""
    global _jwks_client
    import jwt

    with _jwks_lock:
        if _jwks_client is None:
            _jwks_client = jwt.PyJWKClient(JWKS_URL, cache_keys=True)
    return _jwks_client.get_signing_key_from_jwt(token).key


def verify_oidc(token: str, audience: str, key_resolver=None) -> dict:
    import jwt

    resolver = key_resolver or _default_key_resolver
    try:
        key = resolver(token)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=GITHUB_ISSUER,
        )
    except jwt.PyJWTError as exc:
        raise IntakeError(401, f"OIDC token rejected: {exc}") from exc


def authorize(claims: dict, registry: models.Registry) -> str:
    """claims → repo_id. The registry — never the payload — decides the write path."""
    from center_kb.publish import _REPO_ID_RE

    ref = claims.get("ref", "")
    if not ref.startswith(TAG_REF_PREFIX):
        raise IntakeError(
            403, f"ref '{ref}' is not a {TAG_REF_PREFIX}* tag — run `kb publish`"
        )
    repo = claims.get("repository", "")
    rid = registry.repos.get(repo, "")
    if not rid:
        raise IntakeError(
            403,
            f"repo '{repo}' is not registered — open a PR on the hub adding "
            f"`{repo}: <repo-id>` under `repos:` in federation/registry.yaml",
        )
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise IntakeError(500, f"registry maps '{repo}' to invalid repo-id '{rid}'")
    return rid


def safe_extract(data: bytes, dest: Path, max_bytes: int = DEFAULT_MAX_TAR) -> None:
    if len(data) > max_bytes:
        raise IntakeError(413, f"archive exceeds {max_bytes} bytes")
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError as exc:
        raise IntakeError(400, f"archive is not a valid tar.gz: {exc}") from exc
    dest_resolved = dest.resolve()
    with tf:
        total = 0
        for member in tf.getmembers():
            if not member.isreg():
                raise IntakeError(
                    400, f"tar member '{member.name}' is not a regular file"
                )
            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                raise IntakeError(400, f"tar member '{member.name}' escapes dest")
            total += member.size
            if total > max_bytes:
                raise IntakeError(413, f"archive content exceeds {max_bytes} bytes")
            target = (dest / rel).resolve()
            if not target.is_relative_to(dest_resolved):
                raise IntakeError(400, f"tar member '{member.name}' escapes dest")
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            assert src is not None  # isreg() checked above
            target.write_bytes(src.read())


class StatusStore:
    """(repo_id, commit) → {state, pr_url, detail}; thread-safe; optional JSON persistence."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning("intake status file unreadable — starting empty")

    @staticmethod
    def _key(repo_id: str, commit: str) -> str:
        return f"{repo_id}@{commit}"

    def set(
        self, repo_id: str, commit: str, state: str, pr_url: str = "", detail: str = ""
    ) -> None:
        with self._lock:
            self._data[self._key(repo_id, commit)] = {
                "state": state, "pr_url": pr_url, "detail": detail,
            }
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._path.write_text(json.dumps(self._data), encoding="utf-8")

    def get(self, repo_id: str, commit: str) -> dict | None:
        with self._lock:
            return self._data.get(self._key(repo_id, commit))


_repo_locks: dict[str, threading.Lock] = {}
_repo_locks_guard = threading.Lock()


def repo_lock(repo_id: str) -> threading.Lock:
    with _repo_locks_guard:
        return _repo_locks.setdefault(repo_id, threading.Lock())
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_intake_core.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/intake.py tests/test_intake_core.py
git commit -m "feat: intake core — OIDC verify, registry authorize, safe extract, status store"
```

---

### Task 7: `intake.intake_publish` — apply snapshot + App-token PR trên hub

**Files:**
- Modify: `src/center_kb/intake.py`
- Test: `tests/test_intake_publish.py`

**Interfaces:**
- Consumes: `publish._snapshot` (Task 2 — signature `(kb_abs, handle, rid, source_commit, source_url) -> (n_docs, changed)`), `gitio.push_branch_url` (Task 4), `ghapp.mint_installation_token/create_or_get_pr/repo_full_from_url` (Task 5), `hashsync` (Task 1).
- Produces:
  - `intake.IntakeConfig` — dataclass `{hub_ref: str, audience: str, creds: ghapp.AppCreds, status_path: Path | None = None, max_tar_bytes: int = DEFAULT_MAX_TAR, key_resolver = None, http = None, push_via_token_url: bool = True}`
  - `intake.hub_manifest(hub_ref: str, rid: str) -> dict[str, str]` — manifest của `federation/<rid>/` (exclude `_meta.yaml`); hub unreachable → `IntakeError(503)`.
  - `intake.intake_publish(cfg: IntakeConfig, rid: str, source_commit: str, source_repo_full: str, deletes: list[str], archive: bytes) -> str` — trả `pr_url` (`""` nếu không có gì đổi). Toàn bộ chạy trong `repo_lock(rid)`.
  - `push_via_token_url=False` (test seam): push bằng `gitio.push_branch(root, branch)` về origin thường thay vì URL chứa token — hub test là local bare repo, không có GitHub.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_intake_publish.py
from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from center_kb import ghapp, intake


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def hub(tmp_path):
    """Hub = local clone có origin bare — giống hub cache của server."""
    bare = tmp_path / "hub-origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (seed / "federation").mkdir()
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "hub-clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


def _kb_archive() -> bytes:
    buf = io.BytesIO()
    files = {
        "index.yaml": b"docs:\n- id: doc-a\n  title: Doc A\n",
        "doc-a/_manifest.yaml": b"id: doc-a\ntitle: Doc A\nsections: []\n",
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


def _cfg(hub: Path, http) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(hub),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )


def test_intake_publish_creates_branch_and_pr(hub, monkeypatch):
    http = FakeHTTP(
        [
            (200, {"id": 9}),
            (201, {"token": "ghs_t"}),
            (201, {"html_url": "https://github.com/acme/hub/pull/7"}),
        ]
    )
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(
        intake.ghapp, "repo_full_from_url", lambda url: "acme/hub"
    )
    cfg = _cfg(hub, http)
    pr = intake.intake_publish(
        cfg, "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr.endswith("/pull/7")
    # branch publish/flight-docs tồn tại trên origin, chứa snapshot + _meta + index tổng
    _git(hub, "checkout", "publish/flight-docs")
    fed = hub / "federation" / "flight-docs"
    assert (fed / "index.yaml").exists()
    assert (fed / "_meta.yaml").exists()
    meta = (fed / "_meta.yaml").read_text(encoding="utf-8")
    assert "acme/flight-docs" in meta  # source_url từ claims, không từ payload
    assert (hub / "federation" / "index.yaml").exists()
    # về lại main sau khi xong
    _git(hub, "checkout", "main")


def test_intake_publish_nothing_changed_returns_empty(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http1 = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http1), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    # lần 2 nội dung y hệt → không gọi GitHub API nào, trả ""
    http2 = FakeHTTP([])
    pr = intake.intake_publish(
        _cfg(hub, http2), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr == ""
    assert http2.requests == []


def test_intake_publish_applies_deletes(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    responses = [
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
    ]
    http = FakeHTTP(responses)
    cfg = _cfg(hub, http)
    intake.intake_publish(
        cfg, "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # publish 2: xoá doc-a/_manifest.yaml
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs: []\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    intake.intake_publish(
        cfg, "flight-docs", "bbb", "acme/flight-docs",
        ["doc-a/_manifest.yaml"], buf.getvalue(),
    )
    _git(hub, "checkout", "publish/flight-docs")
    assert not (hub / "federation" / "flight-docs" / "doc-a").exists()
    _git(hub, "checkout", "main")


def test_hub_manifest_excludes_meta(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # manifest đọc từ branch main — chưa merge nên rỗng là đúng;
    # đọc từ working tree sau checkout branch thì có file. hub_manifest đọc
    # trạng thái main (đã merge) — mô phỏng bằng merge branch vào main:
    _git(hub, "merge", "publish/flight-docs")
    man = intake.hub_manifest(str(hub), "flight-docs")
    assert "index.yaml" in man
    assert "_meta.yaml" not in man
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_intake_publish.py -v`
Expected: FAIL — `AttributeError: ... no attribute 'IntakeConfig'`

- [ ] **Step 3: Implement** — thêm vào `src/center_kb/intake.py`:

```python
# imports bổ sung ở đầu file:
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from center_kb import federation, ghapp, gitio, hashsync
from center_kb import hub as hub_mod


@dataclass
class IntakeConfig:
    hub_ref: str
    audience: str
    creds: ghapp.AppCreds
    status_path: Path | None = None
    max_tar_bytes: int = DEFAULT_MAX_TAR
    key_resolver: object = None  # test seam — None = PyJWKClient thật
    http: object = None  # test seam — None = urllib thật
    push_via_token_url: bool = True  # False trong test: push origin local


def _resolve_hub_or_503(hub_ref: str) -> hub_mod.HubHandle:
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise IntakeError(503, "hub unreachable from the intake server")
    return handle


def hub_manifest(hub_ref: str, rid: str) -> dict[str, str]:
    handle = _resolve_hub_or_503(hub_ref)
    return hashsync.build_manifest(
        handle.federation_dir / rid, exclude=("_meta.yaml",)
    )


def intake_publish(
    cfg: IntakeConfig,
    rid: str,
    source_commit: str,
    source_repo_full: str,
    deletes: list[str],
    archive: bytes,
) -> str:
    """Apply an uploaded snapshot on branch publish/<rid> and open the hub PR.

    Returns the PR URL, or "" when the snapshot changes nothing.
    """
    from center_kb import publish as publish_mod

    http = cfg.http or ghapp._default_http
    deletes = [d for d in deletes if d != "_meta.yaml"]
    with repo_lock(rid):
        handle = _resolve_hub_or_503(cfg.hub_ref)
        publish_mod._neutralize_excludes(handle.root)
        try:
            gitio.pull(handle.root)  # PR đặt trên main mới nhất khi có thể
        except gitio.GitError:
            logger.warning("hub pull failed — publishing against cached main")
        original = gitio.current_branch(handle.root)
        branch = f"publish/{rid}"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_kb = Path(tmp) / "kb"
            tmp_kb.mkdir()
            safe_extract(archive, tmp_kb, cfg.max_tar_bytes)
            try:
                gitio.checkout_branch(handle.root, branch, original)
                dest = handle.federation_dir / rid
                # upload là incremental: mọi file trong archive coi như changed
                local_man = hashsync.build_manifest(tmp_kb)
                hashsync.apply_sync(tmp_kb, dest, sorted(local_man), deletes)
                committed_probe = gitio.commit_paths(
                    handle.root, "probe", ["federation"]
                )
                if not committed_probe:
                    return ""  # không gì đổi — finally sẽ checkout về original
                # có thay đổi thật: hoàn tác commit probe, viết _meta + index rồi commit chuẩn
                gitio._run(handle.root, "reset", "--soft", "HEAD~1")
                meta = federation.FederationMeta(
                    repo_id=rid,
                    source_url=f"https://github.com/{source_repo_full}",
                    source_commit=source_commit,
                    published_at=datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                )
                from center_kb import models as models_mod

                models_mod.save_yaml_model(dest / "_meta.yaml", meta)
                federation.write_federation_index(handle.federation_dir)
                gitio.commit_paths(
                    handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
                )
                hub_url = gitio.remote_url(handle.root)
                hub_full = ghapp.repo_full_from_url(hub_url)
                token = ghapp.mint_installation_token(cfg.creds, hub_full, http=http)
                if cfg.push_via_token_url:
                    push_url = f"https://x-access-token:{token}@github.com/{hub_full}.git"
                    gitio.push_branch_url(handle.root, push_url, branch)
                else:
                    gitio.push_branch(handle.root, branch)
                return ghapp.create_or_get_pr(
                    hub_full,
                    token,
                    branch,
                    title=f"publish: {rid} @ {source_commit}",
                    body=publish_mod.PR_BODY_TEMPLATE.format(
                        rid=rid, commit=source_commit
                    ),
                    base=original,
                    http=http,
                )
            finally:
                gitio.checkout(handle.root, original)
```

Ghi chú cho engineer: "commit probe" tồn tại vì cần biết *trước khi* viết `_meta.yaml` là snapshot có đổi gì không (viết `_meta` xong mới đo thì `published_at` mới luôn làm tree dirty). Cách rẻ hơn: đo bằng `git status --porcelain -- federation` thay vì commit rồi reset. **Refactor ngay trong step này** thành:

```python
                dirty = gitio._run(
                    handle.root, "status", "--porcelain", "--", "federation"
                ).stdout.strip()
                if not dirty:
                    return ""
```

(bỏ hẳn cặp `commit_paths("probe")` + `reset --soft` — dùng bản `status --porcelain` này, không giữ bản probe.)

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_intake_publish.py tests/test_intake_core.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/intake.py tests/test_intake_publish.py
git commit -m "feat: intake_publish — apply snapshot on publish/<rid>, App-token push + PR"
```

---

### Task 8: HTTP routes `/intake/*` + auth exemption + env wiring

**Files:**
- Create: `src/center_kb/web/intake_routes.py`
- Modify: `src/center_kb/web/app.py`, `src/center_kb/web/auth.py`, `src/center_kb/mcp.py`
- Test: `tests/test_intake_http.py`

**Interfaces:**
- Consumes: toàn bộ Task 6+7 (`verify_oidc`, `authorize`, `intake_publish`, `hub_manifest`, `StatusStore`, `IntakeConfig`), `federation.load_registry` (Task 3).
- Produces:
  - `web.intake_routes.build_intake_routes(cfg: IntakeConfig, store: StatusStore) -> list[Route]` — `GET /intake/manifest?repo_id=`, `GET /intake/status?repo_id=&commit=`, `POST /intake/publish` (multipart: field `meta` = JSON `{"source_commit": str, "deletes": [str]}`, field `archive` = tar.gz).
  - `create_app(config, token, mcp_server=None, intake_cfg=None)` — thêm param; `create_http_app(config, token)` tự build `intake_cfg` từ env.
  - `intake.intake_config_from_env(hub_ref: str) -> IntakeConfig | None` — env `CENTER_KB_GH_APP_ID`, `CENTER_KB_GH_APP_KEY` (path tới PEM), `CENTER_KB_INTAKE_AUDIENCE`; thiếu bất kỳ → `None` + log info; PEM đọc lỗi → `None` + log error (MCP đọc vẫn chạy).
  - `auth.EXEMPT_PREFIXES` thêm `"/intake/"` — child CI không có `CENTER_KB_HTTP_TOKEN`; POST tự bảo vệ bằng OIDC, GET manifest/status là metadata (giả định mạng nội bộ, như spec §4).

- [ ] **Step 1: Write failing tests**

```python
# tests/test_intake_http.py
from __future__ import annotations

import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb import ghapp, intake
from center_kb.web import intake_routes

AUD = "https://kb.test"


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@pytest.fixture
def hub_with_registry(tmp_path):
    """Hub local có registry ánh xạ acme/flight-docs → flight-docs."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    fed = seed / "federation"
    fed.mkdir()
    (fed / "registry.yaml").write_text(
        "repos:\n  acme/flight-docs: flight-docs\n", encoding="utf-8"
    )
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, req):
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


@pytest.fixture
def client(hub_with_registry, keypair, tmp_path, monkeypatch):
    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP(
            [(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]
        ),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    app = Starlette(routes=intake_routes.build_intake_routes(cfg, store))
    return TestClient(app), pem


def _jwt(pem, **overrides):
    now = int(time.time())
    claims = {
        "iss": intake.GITHUB_ISSUER, "aud": AUD, "iat": now, "exp": now + 300,
        "repository": "acme/flight-docs",
        "ref": "refs/tags/kb-publish/20260715-010101",
    }
    claims.update(overrides)
    return pyjwt.encode(claims, pem, algorithm="RS256")


def _archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs:\n- id: doc-a\n  title: A\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _post(client, token, commit="abc1234", deletes=()):
    return client.post(
        "/intake/publish",
        headers={"Authorization": f"Bearer {token}"},
        data={"meta": json.dumps({"source_commit": commit, "deletes": list(deletes)})},
        files={"archive": ("kb.tar.gz", _archive(), "application/gzip")},
    )


def test_publish_happy_path_and_status(client):
    c, pem = client
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 200, resp.text
    assert resp.json()["pr_url"].endswith("/pull/9")
    st = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "abc1234"})
    assert st.status_code == 200
    assert st.json()["state"] == "done"


def test_publish_no_token_401(client):
    c, _ = client
    resp = c.post("/intake/publish")
    assert resp.status_code == 401


def test_publish_unregistered_repo_403(client):
    c, pem = client
    resp = _post(c, _jwt(pem, repository="evil/other"))
    assert resp.status_code == 403
    assert "registry" in resp.json()["detail"]


def test_publish_bad_ref_403(client):
    c, pem = client
    resp = _post(c, _jwt(pem, ref="refs/heads/main"))
    assert resp.status_code == 403


def test_manifest_unknown_repo_returns_empty(client):
    c, _ = client
    resp = c.get("/intake/manifest", params={"repo_id": "flight-docs"})
    assert resp.status_code == 200
    assert resp.json() == {"files": {}}


def test_status_unknown_404(client):
    c, _ = client
    resp = c.get("/intake/status", params={"repo_id": "x", "commit": "y"})
    assert resp.status_code == 404


def test_auth_middleware_exempts_intake():
    from center_kb.web import auth

    assert "/intake/" in auth.EXEMPT_PREFIXES


def test_intake_config_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_GH_APP_ID", raising=False)
    assert intake.intake_config_from_env("hub") is None
    pem_path = tmp_path / "app.pem"
    pem_path.write_text("PEM", encoding="utf-8")
    monkeypatch.setenv("CENTER_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("CENTER_KB_GH_APP_KEY", str(pem_path))
    monkeypatch.setenv("CENTER_KB_INTAKE_AUDIENCE", AUD)
    cfg = intake.intake_config_from_env("hub")
    assert cfg is not None
    assert cfg.creds.app_id == "1234"
    assert cfg.creds.private_key_pem == "PEM"
    assert cfg.audience == AUD
    # PEM path hỏng → None (fail closed), không raise
    monkeypatch.setenv("CENTER_KB_GH_APP_KEY", str(tmp_path / "missing.pem"))
    assert intake.intake_config_from_env("hub") is None
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_intake_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.web.intake_routes'`

- [ ] **Step 3: Implement**

```python
# src/center_kb/web/intake_routes.py
from __future__ import annotations

import json

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import federation, ghapp, gitio, intake
from center_kb import hub as hub_mod


def _err(exc: intake.IntakeError) -> JSONResponse:
    return JSONResponse(
        {"error": "intake_rejected", "detail": exc.detail}, status_code=exc.status
    )


def build_intake_routes(
    cfg: intake.IntakeConfig, store: intake.StatusStore
) -> list[Route]:
    async def manifest(request: Request) -> JSONResponse:
        rid = request.query_params.get("repo_id", "")
        if not rid:
            return JSONResponse(
                {"error": "missing_repo_id", "detail": "query param repo_id required"},
                status_code=400,
            )
        try:
            files = await run_in_threadpool(intake.hub_manifest, cfg.hub_ref, rid)
        except intake.IntakeError as exc:
            return _err(exc)
        return JSONResponse({"files": files})

    async def status(request: Request) -> JSONResponse:
        rid = request.query_params.get("repo_id", "")
        commit = request.query_params.get("commit", "")
        found = store.get(rid, commit)
        if found is None:
            return JSONResponse({"state": "unknown"}, status_code=404)
        return JSONResponse(found)

    async def publish(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"error": "missing_token", "detail": "Authorization: Bearer <OIDC JWT> required"},
                status_code=401,
            )
        token = auth.removeprefix("Bearer ")
        try:
            claims = await run_in_threadpool(
                intake.verify_oidc, token, cfg.audience, cfg.key_resolver
            )

            def _load_registry():
                handle = hub_mod.resolve_hub(cfg.hub_ref)
                if handle is None:
                    raise intake.IntakeError(503, "hub unreachable")
                return federation.load_registry(handle.federation_dir)

            try:
                registry = await run_in_threadpool(_load_registry)
            except federation.RegistryError as exc:
                raise intake.IntakeError(503, str(exc))
            rid = intake.authorize(claims, registry)
            form = await request.form()
            try:
                meta = json.loads(form["meta"])
                source_commit = str(meta["source_commit"])
                deletes = [str(d) for d in meta.get("deletes", [])]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise intake.IntakeError(
                    400, "field 'meta' must be JSON with source_commit (+ optional deletes)"
                )
            upload = form.get("archive")
            if upload is None:
                raise intake.IntakeError(400, "multipart field 'archive' required")
            archive = await upload.read()
        except intake.IntakeError as exc:
            return _err(exc)

        store.set(rid, source_commit, "processing")
        try:
            pr_url = await run_in_threadpool(
                intake.intake_publish,
                cfg, rid, source_commit, claims["repository"], deletes, archive,
            )
        except intake.IntakeError as exc:
            store.set(rid, source_commit, "error", detail=exc.detail)
            return _err(exc)
        except (gitio.GitError, ghapp.GHAppError) as exc:
            store.set(rid, source_commit, "error", detail=str(exc))
            return JSONResponse(
                {"error": "publish_failed", "detail": str(exc)}, status_code=502
            )
        store.set(rid, source_commit, "done", pr_url=pr_url)
        return JSONResponse({"repo_id": rid, "pr_url": pr_url})

    return [
        Route("/intake/manifest", manifest, methods=["GET"]),
        Route("/intake/status", status, methods=["GET"]),
        Route("/intake/publish", publish, methods=["POST"]),
    ]
```

`web/auth.py` — sửa:

```python
EXEMPT_PREFIXES = ("/ui/static/", "/intake/")
```

`intake.py` — thêm:

```python
def intake_config_from_env(hub_ref: str) -> IntakeConfig | None:
    """Build IntakeConfig from env; None (intake disabled, read server still runs)
    when any of the three vars is missing or the PEM is unreadable."""
    import os

    app_id = os.environ.get("CENTER_KB_GH_APP_ID", "")
    key_path = os.environ.get("CENTER_KB_GH_APP_KEY", "")
    audience = os.environ.get("CENTER_KB_INTAKE_AUDIENCE", "")
    if not (app_id and key_path and audience):
        logger.info(
            "intake disabled — set CENTER_KB_GH_APP_ID, CENTER_KB_GH_APP_KEY, "
            "CENTER_KB_INTAKE_AUDIENCE to enable /intake/publish"
        )
        return None
    try:
        pem = Path(key_path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("intake disabled — cannot read App key '%s': %s", key_path, exc)
        return None
    return IntakeConfig(
        hub_ref=hub_ref,
        audience=audience,
        creds=ghapp.AppCreds(app_id=app_id, private_key_pem=pem),
        status_path=hub_mod._cache_base() / "intake-status.json",
    )
```

`web/app.py` — signature + routes:

```python
def create_app(config: ServerConfig, token: str, mcp_server=None, intake_cfg=None):
    ...
    routes: list = [Route("/", root, methods=["GET"])]
    routes += api.build_routes(config)
    routes += ui.build_routes(config, token)
    if intake_cfg is not None:
        from center_kb import intake as intake_mod
        from center_kb.web import intake_routes

        store = intake_mod.StatusStore(intake_cfg.status_path)
        routes += intake_routes.build_intake_routes(intake_cfg, store)
```

`mcp.py::create_http_app`:

```python
def create_http_app(config: ServerConfig, token: str):
    """One ASGI app: MCP (streamable HTTP) + REST /api + HTML /ui + /intake, token-guarded."""
    from center_kb.intake import intake_config_from_env
    from center_kb.web.app import create_app

    return create_app(
        config, token,
        mcp_server=create_server(config),
        intake_cfg=intake_config_from_env(config.hub),
    )
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_intake_http.py tests/test_mcp_http.py tests/test_web_api.py -v`
Expected: PASS toàn bộ (route cũ không vỡ).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/web/ src/center_kb/intake.py src/center_kb/mcp.py tests/test_intake_http.py
git commit -m "feat: /intake HTTP routes — OIDC-authed publish, manifest, status"
```

---

### Task 9: CLI — intake mode cho `kb publish` + `kb ci-publish`

**Files:**
- Modify: `src/center_kb/config.py` (field `intake`), `src/center_kb/publish.py` (`publish_via_intake`), `src/center_kb/cli.py`
- Create: `src/center_kb/cipublish.py`
- Test: `tests/test_publish_intake_cli.py`

**Interfaces:**
- Consumes: `gitio.tag/push_tag` (Task 4), `hashsync` (Task 1).
- Produces:
  - `config.KBConfig.intake: str = ""` — URL intake trong `.kb/config.yaml`.
  - `publish.publish_via_intake(kb_dir: Path, intake_url: str, repo_id: str | None, poll_interval: float = 5.0, timeout: float = 600.0, http_get_json=None) -> str` — dirty check → tag `kb-publish/<UTC %Y%m%d-%H%M%S>` → push tag → poll `GET <intake>/intake/status` → trả `pr_url`; state `error` hoặc timeout → `PublishError`. `http_get_json: Callable[[str], tuple[int, dict]]` (test seam; None = urllib).
  - `cipublish.run(kb_dir: Path, intake_url: str, repo_id: str | None, http=None, token_requester=None) -> str` — trả `pr_url` hoặc `""` (nothing to publish). Chạy trong GitHub Actions: OIDC qua env `ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN`; manifest diff; tarball changed; POST multipart.
  - CLI: `kb publish` — config có `intake` và không có `--pr/--direct` → gọi `publish_via_intake`; `kb ci-publish` — command mới gọi `cipublish.run`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_publish_intake_cli.py
from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from center_kb import cipublish, gitio
from center_kb import publish as publish_mod


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def child(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    kb = root / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    bare = tmp_path / "child-origin.git"
    _git(tmp_path, "clone", "--bare", str(root), str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    return root, bare


class TestPublishViaIntake:
    def test_dirty_kb_raises_before_tagging(self, child):
        root, _ = child
        (root / ".kb" / "new.md").write_text("x", encoding="utf-8")
        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(root / ".kb", "https://kb.test", "child")
        assert "commit" in str(exc.value).lower()
        assert "kb-publish/" not in _git(root, "tag", "--list")

    def test_happy_path_tags_pushes_polls(self, child):
        root, bare = child
        calls = []

        def fake_get(url):
            calls.append(url)
            return 200, {"state": "done", "pr_url": "https://gh/pull/4", "detail": ""}

        pr = publish_mod.publish_via_intake(
            root / ".kb", "https://kb.test", "child-a",
            poll_interval=0, timeout=5, http_get_json=fake_get,
        )
        assert pr == "https://gh/pull/4"
        tags = _git(bare, "tag", "--list")
        assert "kb-publish/" in tags
        assert "repo_id=child-a" in calls[0]
        commit = gitio.head_commit(root)
        assert f"commit={commit}" in calls[0]

    def test_error_state_raises_with_detail(self, child):
        root, _ = child

        def fake_get(url):
            return 200, {"state": "error", "pr_url": "", "detail": "boom"}

        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(
                root / ".kb", "https://kb.test", "child-a",
                poll_interval=0, timeout=5, http_get_json=fake_get,
            )
        assert "boom" in str(exc.value)

    def test_timeout_raises_actionable(self, child):
        root, _ = child

        def fake_get(url):
            return 404, {"state": "unknown"}

        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(
                root / ".kb", "https://kb.test", "child-a",
                poll_interval=0, timeout=0.1, http_get_json=fake_get,
            )
        assert "Actions" in str(exc.value)


class FakeHTTP:
    """(method, url) → (status, json-dict). Ghi lại body POST."""

    def __init__(self, table):
        self.table = table
        self.posted = []

    def __call__(self, method, url, headers, body):
        if method == "POST":
            self.posted.append((url, headers, body))
        for prefix, resp in self.table.items():
            if url.startswith(prefix):
                return resp[0], json.dumps(resp[1]).encode()
        raise AssertionError(f"unexpected url {url}")


class TestCIPublish:
    def _env(self, monkeypatch):
        monkeypatch.setenv(
            "ACTIONS_ID_TOKEN_REQUEST_URL", "https://actions.local/token?x=1"
        )
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "req-tok")

    def test_nothing_to_publish_when_manifest_matches(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        from center_kb import hashsync

        local = hashsync.build_manifest(root / ".kb")
        http = FakeHTTP({"https://kb.test/intake/manifest": (200, {"files": local})})
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == ""
        assert http.posted == []

    def test_posts_changed_files_and_returns_pr(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (200, {"files": {}}),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/8"},
                ),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == "https://gh/pull/8"
        url, headers, body = http.posted[0]
        assert headers["Authorization"] == "Bearer oidc-jwt"
        # body multipart chứa index.yaml trong archive
        assert b"index.yaml" in body

    def test_manifest_endpoint_down_falls_back_to_full_upload(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (503, {"detail": "down"}),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/8"},
                ),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == "https://gh/pull/8"  # vẫn publish, upload full
```

- [ ] **Step 2: Run, verify FAIL**

Run: `python -m pytest tests/test_publish_intake_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.cipublish'`

- [ ] **Step 3: Implement**

`config.py` — `KBConfig` thêm field:

```python
class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""
    kind: Literal["", "hub", "child"] = ""
    intake: str = ""  # intake service base URL — child publishes qua OIDC CI
```

`publish.py` — thêm cuối file:

```python
def _default_get_json(url: str) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            import json as json_mod

            return resp.status, json_mod.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except OSError:
        return 0, {}


def publish_via_intake(
    kb_dir: Path,
    intake_url: str,
    repo_id: str | None,
    poll_interval: float = 5.0,
    timeout: float = 600.0,
    http_get_json=None,
) -> str:
    """Dev-machine intake flow: tag kb-publish/<ts>, push, poll for the PR URL.

    Zero secrets: the tag push uses the developer's normal child-repo git
    access; the child's CI (OIDC) does the actual upload.
    """
    import time as time_mod
    import urllib.parse

    get_json = http_get_json or _default_get_json
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.is_dirty(root, kb_abs):
        raise PublishError(
            ".kb/ has uncommitted changes — commit them first "
            "(the child CI publishes the tagged commit, not the working tree)"
        )
    rid = repo_id or root.name
    commit = gitio.head_commit(root)
    tag_name = f"kb-publish/{datetime.now(timezone.utc):%Y%m%d-%H%M%S}"
    gitio.tag(root, tag_name)
    gitio.push_tag(root, tag_name)
    status_url = (
        f"{intake_url.rstrip('/')}/intake/status?"
        + urllib.parse.urlencode({"repo_id": rid, "commit": commit})
    )
    deadline = time_mod.monotonic() + timeout
    while time_mod.monotonic() <= deadline:
        status, data = get_json(status_url)
        if status == 200:
            if data.get("state") == "done":
                return data.get("pr_url", "")
            if data.get("state") == "error":
                raise PublishError(f"intake rejected the publish: {data.get('detail')}")
        if poll_interval:
            time_mod.sleep(poll_interval)
        elif status != 200:
            break  # test mode (poll_interval=0): một vòng là đủ khi chưa có status
    raise PublishError(
        f"timed out waiting for the intake — check the Actions run for tag "
        f"'{tag_name}' in the child repo's GitHub Actions logs"
    )
```

`cipublish.py` — mới:

```python
# src/center_kb/cipublish.py
"""kb ci-publish — runs inside the child's GitHub Actions job.

OIDC JWT ← ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN; manifest diff against the hub
(via the intake service); uploads only changed files + a delete list.
No static secret anywhere in the child repo.
"""
from __future__ import annotations

import io
import json
import os
import tarfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from center_kb import gitio, hashsync


class CIPublishError(RuntimeError):
    """ci-publish failed — the Actions job should go red."""


def _default_http(method: str, url: str, headers: dict, body: bytes | None):
    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _request_oidc_token(audience: str, http) -> str:
    req_url = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL", "")
    req_tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "")
    if not req_url or not req_tok:
        raise CIPublishError(
            "not inside GitHub Actions (ACTIONS_ID_TOKEN_REQUEST_* missing) — "
            "ci-publish only runs in the child's workflow; use `kb publish` locally"
        )
    url = f"{req_url}&audience={urllib.parse.quote(audience, safe='')}"
    status, raw = http("GET", url, {"Authorization": f"Bearer {req_tok}"}, None)
    if status != 200:
        raise CIPublishError(f"OIDC token request failed: HTTP {status}")
    return json.loads(raw)["value"]


def _fetch_remote_manifest(intake_url: str, rid: str, http) -> dict[str, str]:
    url = (
        f"{intake_url.rstrip('/')}/intake/manifest?"
        + urllib.parse.urlencode({"repo_id": rid})
    )
    status, raw = http("GET", url, {}, None)
    if status != 200:
        print(f"[warn] manifest endpoint returned {status} — falling back to full upload")
        return {}
    return json.loads(raw).get("files", {})


def _build_archive(kb_abs: Path, changed: list[str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel in changed:
            tf.add(kb_abs / rel, arcname=rel)
    return buf.getvalue()


def _multipart(meta: dict, archive: bytes) -> tuple[bytes, str]:
    boundary = f"kb-{uuid.uuid4().hex}"
    meta_json = json.dumps(meta).encode("utf-8")
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="meta"\r\n\r\n',
            meta_json, b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="archive"; filename="kb.tar.gz"\r\n',
            b"Content-Type: application/gzip\r\n\r\n",
            archive, b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return body, f"multipart/form-data; boundary={boundary}"


def run(
    kb_dir: Path,
    intake_url: str,
    repo_id: str | None,
    http=None,
    token_requester=None,
) -> str:
    """Diff → upload → return PR URL; "" when there is nothing to publish."""
    http = http or _default_http
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    rid = repo_id or root.name
    commit = gitio.head_commit(root)

    remote_man = _fetch_remote_manifest(intake_url, rid, http)
    local_man = hashsync.build_manifest(kb_abs)
    changed, deleted = hashsync.diff_manifests(local_man, remote_man)
    if not changed and not deleted:
        print("nothing to publish — hub snapshot already matches .kb/")
        return ""
    print(f"publishing {len(changed)} changed file(s), {len(deleted)} deletion(s)")

    audience = intake_url.rstrip("/")
    token = (token_requester or _request_oidc_token)(audience, http)
    archive = _build_archive(kb_abs, changed)
    body, content_type = _multipart(
        {"source_commit": commit, "deletes": deleted}, archive
    )
    status, raw = http(
        "POST",
        f"{intake_url.rstrip('/')}/intake/publish",
        {"Authorization": f"Bearer {token}", "Content-Type": content_type},
        body,
    )
    if status != 200:
        try:
            detail = json.loads(raw).get("detail", "")
        except (json.JSONDecodeError, AttributeError):
            detail = raw[:200] if isinstance(raw, bytes) else str(raw)
        raise CIPublishError(f"intake rejected the publish (HTTP {status}): {detail}")
    pr_url = json.loads(raw).get("pr_url", "")
    print(f"PR: {pr_url}" if pr_url else "published (no content change on the hub)")
    return pr_url
```

Lưu ý test seam: trong test, `token_requester` không được truyền — `_request_oidc_token` chạy thật nhưng `http` fake trả `{"value": "oidc-jwt"}` — đúng như `TestCIPublish` mong đợi.

`cli.py` — trong `publish()` command, ngay sau đoạn check `pr and direct`:

```python
    from center_kb.config import load_config

    cfg = load_config(kb_dir)
    if cfg.intake and not pr and not direct:
        from center_kb import publish as publish_mod
        from center_kb.config import effective_repo_id

        try:
            pr_url = publish_mod.publish_via_intake(
                kb_dir, cfg.intake, effective_repo_id(repo_id, kb_dir)
            )
        except (publish_mod.PublishError, gitio.GitError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
        if pr_url:
            typer.echo(f"kb publish: PR on the hub — {pr_url}")
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: done (no PR URL reported).")
        return
```

`cli.py` — command mới (đặt cạnh `publish`):

```python
@app.command(name="ci-publish")
def ci_publish(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID on the hub (default: config)"),
    intake: str = typer.Option(
        "", "--intake", envvar="CENTER_KB_INTAKE",
        help="Intake base URL (default: .kb/config.yaml `intake:`)",
    ),
) -> None:
    """Publish from the child's CI via OIDC — no secrets. Run by kb-publish.yml."""
    from center_kb import cipublish, gitio
    from center_kb.config import effective_repo_id, load_config

    url = intake or load_config(kb_dir).intake
    if not url:
        typer.secho(
            "no intake URL — add `intake: <url>` to .kb/config.yaml or pass --intake",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    try:
        cipublish.run(kb_dir, url, effective_repo_id(repo_id, kb_dir))
    except (cipublish.CIPublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

- [ ] **Step 4: Run, verify PASS**

Run: `python -m pytest tests/test_publish_intake_cli.py tests/test_cli_hub.py -v`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/config.py src/center_kb/publish.py src/center_kb/cipublish.py src/center_kb/cli.py tests/test_publish_intake_cli.py
git commit -m "feat: kb publish intake mode (tag+poll) + kb ci-publish (OIDC upload)"
```

---

### Task 10: Templates + docs + registry scaffold

**Files:**
- Modify: `src/center_kb/templates/init/kb-publish.yml`, `src/center_kb/templates/init/config-child.yaml`, `src/center_kb/templates/init/QUICKSTART-child.md`, `src/center_kb/templates/init/QUICKSTART-hub.md`
- Modify: `docs/deploy-remote-mcp.md`
- Test: `tests/test_init.py` (sửa assertion nếu có test check nội dung template)

- [ ] **Step 1: Rewrite `templates/init/kb-publish.yml`**

```yaml
# CI publishes to the kb-hub via the intake service — OIDC, zero secrets.
# Trigger: `kb publish` on a dev machine creates and pushes a kb-publish/* tag.
# Requirements: `intake: <url>` in .kb/config.yaml (committed). No GH_TOKEN,
# no KB_HUB_URL — the intake service holds the only hub credential.
name: kb-publish
on:
  push:
    tags: ["kb-publish/*"]
permissions:
  id-token: write   # OIDC JWT — proves "I am this repo's workflow" to the intake
  contents: read
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install center-kb
      - name: Publish snapshot → PR on the hub (via intake)
        run: kb ci-publish
```

- [ ] **Step 2: `config-child.yaml`** — thêm dòng (giữ nội dung sẵn có):

```yaml
# intake: https://kb.internal:8321   # bật publish qua OIDC CI (zero secret trên repo này)
```

- [ ] **Step 3: Update docs**

`docs/deploy-remote-mcp.md` — thêm section sau phần systemd:

```markdown
## Publish intake (OIDC → PR on the hub)

The same server can accept publishes from child repos with **zero secrets on
the children**. Child CI authenticates with a GitHub Actions OIDC JWT; the
server verifies it, checks `federation/registry.yaml` on the hub, and opens
the PR itself using a GitHub App.

1. Create a GitHub App (hub owner): permissions `Contents: Read and write` +
   `Pull requests: Read and write`; install it on the hub repo only.
   Download the private key PEM.
2. Extra env for the server:

       Environment=CENTER_KB_GH_APP_ID=<app id>
       Environment=CENTER_KB_GH_APP_KEY=/etc/center-kb/app-key.pem
       Environment=CENTER_KB_INTAKE_AUDIENCE=https://kb.internal:8321

   All three present → `/intake/*` routes turn on. Any missing → intake stays
   off, read-only MCP still works.
3. Register each child on the hub: add `owner/repo: repo-id` under `repos:`
   in `federation/registry.yaml` (a normal PR — also your review gate for who
   may contribute).
4. Install deps on the server: `pip install "center-kb[server]"`.

`/intake/*` is exempt from `CENTER_KB_HTTP_TOKEN` (children don't hold that
token): POST /intake/publish is OIDC-authenticated; GET manifest/status carry
only path+hash metadata — same internal-network assumption as the MCP itself.
```

`QUICKSTART-child.md` — thay đoạn nói về publish/secrets bằng flow mới: `.kb/config.yaml` có `intake:`, `kb publish` = commit → tag → CI mở PR; xóa hướng dẫn `GH_TOKEN`/`KB_HUB_URL` secrets. `QUICKSTART-hub.md` — thêm mục "Đăng ký repo con": tạo `federation/registry.yaml`, mỗi child một dòng `owner/repo: repo-id`, cài GitHub App.

- [ ] **Step 4: Fix template tests**

Run: `python -m pytest tests/test_init.py -v`
Nếu FAIL vì assertion nội dung template cũ (vd check `GH_TOKEN` hay `branches: [main]` trong `kb-publish.yml`): cập nhật assertion theo template mới, vd:

```python
assert 'tags: ["kb-publish/*"]' in content
assert "id-token: write" in content
assert "GH_TOKEN" not in content
```

Expected sau sửa: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/ docs/deploy-remote-mcp.md tests/test_init.py
git commit -m "docs: intake templates — OIDC workflow, registry setup, server env"
```

---

### Task 11: Verification — full suite + gate

- [ ] **Step 1: Full test run**

Run: `python -m pytest --cov=src --cov-report=term-missing`
Expected: PASS toàn bộ; coverage tổng ≥80%; các module mới (`hashsync`, `intake`, `ghapp`, `cipublish`) mỗi module ≥80%.

- [ ] **Step 2: Gate tests (golden)**

Run: `python -m pytest tests-gate -v`
Expected: PASS — đường đọc (search/get_section/MCP) không đổi nên golden phải khớp nguyên trạng. Nếu lệch → điều tra, không regen golden khi chưa hiểu nguyên nhân.

- [ ] **Step 3: Windows sanity (nếu đang trên Windows — môi trường này là Windows)**

Run: `python -m pytest tests/test_hashsync.py tests/test_intake_publish.py -v`
Expected: PASS — đặc biệt test read-only unlink (Windows attribute) và path resolve.

- [ ] **Step 4: Commit cuối (nếu còn diff lặt vặt) + báo cáo**

```bash
git status --short
```

Expected: sạch. Báo cáo kết quả suite + coverage cho reviewer.

---

## Self-Review (đã chạy)

- **Spec coverage:** tiêu chí 1 (dev zero secret, in PR URL) → Task 9; tiêu chí 2 (child zero secret) → Task 10 template; tiêu chí 3 (App key server-side, token ngắn hạn) → Task 5+7; tiêu chí 4 (chống mạo danh — rid từ registry) → Task 6 `authorize`; tiêu chí 5 (đăng ký = PR registry) → Task 3+10; tiêu chí 6 (direct/PR mode giữ nguyên) → Task 2 giữ nguyên flow; tiêu chí 7 (incremental + no-op) → Task 1+2+7+9. Error table spec §6: từng dòng có handler trong Task 6/7/8/9. Security spec §4: JWT sig/iss/aud/exp → Task 6; ref check → Task 6; payload cap + traversal + symlink + delete-list guard → Task 1+6; token không vào log → Task 4 (scrub) + Task 5 (message không chứa token).
- **Type consistency:** `_snapshot` trả `(int, bool)` — cả 2 caller cập nhật ở Task 2; `IntakeConfig.http/key_resolver` seam dùng nhất quán Task 7/8; `StatusStore.get` trả `dict | None` — route 404 khi None.
- **Không placeholder:** mọi step có code/lệnh/expected đầy đủ.
