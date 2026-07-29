# Multi-tier Federation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Một repo `kind: hub` publish được `federation/` của nó lên một hub cấp cao hơn — topology phân tầng sâu tuỳ ý, có chống cycle.

**Architecture:** Đệ quy hoá walk `federation/` (leaf entry = thư mục có `_meta.yaml` + `index.yaml`, id = path tương đối như `mid/repo-x`); `kb publish` trên hub-kind mirror `federation/` (trừ index/registry tầng đỉnh) lên `federation/<hub-id>/` của hub trên, tái dùng nguyên đường `_publish_direct`/`_publish_pr` qua tham số `snapshot_fn`; cycle guard 2 lớp chạy trước khi ghi.

**Tech Stack:** Python 3.13, pydantic, typer, pytest. Venv: `source .venv/bin/activate` (hoặc `python3.13 -m venv .venv` nếu chưa có).

**Spec:** `docs/superpowers/specs/2026-07-28-multi-tier-federation-design.md`

## Global Constraints

- Hub phẳng (không `hub:` trong config) hành xử byte-một-byte như hiện tại; `tests-gate/regression/` phải xanh không sửa fixture.
- `.kb/` riêng của hub KHÔNG được đẩy lên trên — chỉ `federation/`.
- Không viết `_meta.yaml` ở gốc entry hub trên hub cấp trên (`federation/<hub-id>/_meta.yaml` không tồn tại; `_meta.yaml` của các leaf entry bên trong mirror verbatim).
- Cú pháp qualifier cũ `repo-id:doc-id` = trường hợp đặc biệt của `path/lồng:doc-id` — không breaking.
- Tests hermetic: conftest autouse `_no_real_embedder` đã lo, không cần network/model thật.
- Thông báo lỗi cycle phải chứa đúng chuỗi `federation cycle detected`.
- Repo dùng black/isort/ruff; type annotations trên mọi signature mới.

---

### Task 1: Recursive federation walk + path-based repo ids

**Files:**
- Modify: `src/center_kb/federation.py` (thay `load_federation`, thêm `iter_entry_dirs`)
- Test: `tests/test_federation_nested.py` (mới)

**Interfaces:**
- Produces: `federation.iter_entry_dirs(federation_dir: Path) -> list[tuple[str, Path]]` — `(path_id, dir)` mọi leaf entry, path_id dạng posix `mid/repo-x`, thứ tự DFS tên tăng dần. `load_federation` trả `FederatedRepo` với `meta.repo_id` = path_id (đè giá trị trong file bằng `model_copy`). `build_federation_index` không đổi signature — tự nhận entry lồng qua `load_federation`.
- Consumes: schema hiện có (`FederationMeta`, `models.KBIndex`).

- [ ] **Step 1: Viết test fail**

```python
# tests/test_federation_nested.py
from pathlib import Path

from center_kb import federation
from tests.conftest import make_fed_entry


def _make_nested_hub(tmp_path: Path) -> Path:
    """federation/ có 1 entry phẳng + 2 entry lồng dưới namespace mid/."""
    fed = tmp_path / "hub" / "federation"
    make_fed_entry(fed, "repo-flat", "flat-doc")
    make_fed_entry(fed / "mid", "repo-x", "doc-x")
    make_fed_entry(fed / "mid", "repo-y", "doc-y")
    return fed


def test_iter_entry_dirs_finds_flat_and_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert ids == ["mid/repo-x", "mid/repo-y", "repo-flat"]


def test_load_federation_uses_path_id_for_nested_entries(tmp_path):
    fed = _make_nested_hub(tmp_path)
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["mid/repo-x", "mid/repo-y", "repo-flat"]
    # kb_dir trỏ đúng thư mục lồng
    assert repos[0].kb_dir == fed / "mid" / "repo-x"


def test_build_federation_index_includes_nested(tmp_path):
    fed = _make_nested_hub(tmp_path)
    idx = federation.build_federation_index(fed)
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("mid/repo-x", "doc-x"),
        ("mid/repo-y", "doc-y"),
        ("repo-flat", "flat-doc"),
    }


def test_namespace_dir_without_meta_is_not_an_entry(tmp_path):
    fed = _make_nested_hub(tmp_path)
    # thư mục mid/ không có _meta.yaml/index.yaml → namespace, không phải entry
    assert all(pid != "mid" for pid, _ in federation.iter_entry_dirs(fed))


def test_half_broken_entry_is_skipped_with_warning(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    broken = fed / "mid" / "repo-broken"
    broken.mkdir()
    (broken / "index.yaml").write_text("docs: []\n", encoding="utf-8")  # thiếu _meta.yaml
    ids = [pid for pid, _ in federation.iter_entry_dirs(fed)]
    assert "mid/repo-broken" not in ids
    assert any("mid/repo-broken" in r.message for r in caplog.records)


def test_old_slim_layout_still_skipped(tmp_path, caplog):
    fed = _make_nested_hub(tmp_path)
    slim = fed / "repo-old"
    (slim / "manifests").mkdir(parents=True)
    assert all(pid != "repo-old" for pid, _ in federation.iter_entry_dirs(fed))
    assert any("slim layout" in r.message for r in caplog.records)
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_federation_nested.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.federation' has no attribute 'iter_entry_dirs'`

- [ ] **Step 3: Implement**

Trong `src/center_kb/federation.py`, thêm sau `load_registry` và thay toàn bộ hàm `load_federation`:

```python
ENTRY_INDEX_NAME = "index.yaml"
ENTRY_META_NAME = "_meta.yaml"


def iter_entry_dirs(federation_dir: Path) -> list[tuple[str, Path]]:
    """(path-id, dir) của mọi leaf entry, DFS theo tên tăng dần.

    Leaf = thư mục có cả _meta.yaml lẫn index.yaml (một mirror .kb đầy đủ).
    Thư mục phía trên leaf là namespace thuần (một tầng cho mỗi hub publish lên).
    Entry slim cũ (Phase 3, thư mục 'manifests/') và entry thiếu một trong hai
    file bị bỏ qua kèm cảnh báo — republish từ repo nguồn để nâng cấp.
    """
    out: list[tuple[str, Path]] = []

    def _walk(cur: Path, rel: str) -> None:
        for child in sorted(p for p in cur.iterdir() if p.is_dir()):
            child_rel = f"{rel}/{child.name}" if rel else child.name
            if (child / "manifests").is_dir():
                logger.warning(
                    "federation/%s uses the old slim layout — skipping; "
                    "run `kb publish` from that repo to upgrade it",
                    child_rel,
                )
                continue
            has_meta = (child / ENTRY_META_NAME).exists()
            has_index = (child / ENTRY_INDEX_NAME).exists()
            if has_meta and has_index:
                out.append((child_rel, child))
            elif has_meta or has_index:
                logger.warning(
                    "federation/%s missing _meta.yaml or index.yaml — skipping",
                    child_rel,
                )
            else:
                _walk(child, child_rel)

    if federation_dir.is_dir():
        _walk(federation_dir, "")
    return out


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Đọc mọi entry (phẳng lẫn lồng) trong layout mirror.

    meta.repo_id được đè bằng path-id tương đối (vd 'mid/repo-x') — file
    _meta.yaml mirror từ tầng dưới chỉ biết tên cụt của chính nó.
    """
    repos: list[FederatedRepo] = []
    for path_id, child in iter_entry_dirs(federation_dir):
        try:
            meta = models.load_yaml_model(child / ENTRY_META_NAME, FederationMeta)
            index = models.load_yaml_model(child / ENTRY_INDEX_NAME, models.KBIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            logger.warning("federation/%s is broken — skipping: %s", path_id, exc)
            continue
        repos.append(
            FederatedRepo(
                meta=meta.model_copy(update={"repo_id": path_id}),
                index=index,
                kb_dir=child,
            )
        )
    return repos
```

Giữ nguyên `build_federation_index` và `write_federation_index` (tự hưởng lợi qua `load_federation`).

- [ ] **Step 4: Chạy test mới + toàn bộ test liên quan**

Run: `pytest tests/test_federation_nested.py tests/test_federation.py tests/test_federation_e2e.py tests/test_searchdb.py tests/test_query.py tests/test_doctor_hub.py -q`
Expected: PASS toàn bộ (flat không đổi hành vi; searchdb/query/doctor dùng `meta.repo_id` nên tự đúng với id lồng).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/federation.py tests/test_federation_nested.py
git commit -m "feat: recursive federation walk — nested entries get path-based repo ids"
```

---

### Task 2: Qualifier lồng tầng trong refs (`mid/repo-x:doc-id`)

**Files:**
- Modify: `src/center_kb/kbcontext.py:38-41` (`_REF_RE`)
- Test: `tests/test_kbcontext.py` (thêm test), `tests/test_query.py` (thêm test)

**Interfaces:**
- Consumes: `load_federation` trả `meta.repo_id` dạng path (Task 1).
- Produces: `kbcontext.parse_ref("mid/repo-x:doc §1.1")` trả `KBRef(repo_id="mid/repo-x", doc_id="doc", section_id="1.1")`. `query.get_section(hub, "mid/repo-x:doc", "1.1")` hoạt động (code `get_section` đã `split(":", 1)` — không cần sửa, chỉ khoá bằng test).

- [ ] **Step 1: Viết test fail**

Thêm vào cuối `tests/test_kbcontext.py`:

```python
def test_parse_ref_nested_repo_qualifier():
    from center_kb.kbcontext import parse_ref

    ref = parse_ref("mid/repo-x:doc-a §1.1")
    assert ref.repo_id == "mid/repo-x"
    assert ref.doc_id == "doc-a"
    assert ref.section_id == "1.1"
    assert str(ref) == "mid/repo-x:doc-a §1.1"


def test_parse_ref_flat_qualifier_unchanged():
    from center_kb.kbcontext import parse_ref

    ref = parse_ref("repo-x:doc-a §1.1")
    assert ref.repo_id == "repo-x"
```

Thêm vào cuối `tests/test_query.py`:

```python
def test_get_section_nested_qualifier(tmp_path):
    from center_kb.hub import HubHandle
    from center_kb.query import get_section
    from tests.conftest import make_fed_entry

    hub_root = tmp_path / "hub"
    make_fed_entry(hub_root / "federation" / "mid", "repo-x", "doc-x")
    handle = HubHandle(root=hub_root)
    r = get_section(handle, "mid/repo-x:doc-x", "1.1")
    assert r is not None
    assert r.source == "mid/repo-x"
    assert r.citation.startswith("mid/repo-x:doc-x §1.1")
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_kbcontext.py::test_parse_ref_nested_repo_qualifier tests/test_query.py::test_get_section_nested_qualifier -v`
Expected: test kbcontext FAIL (`KBContextError: ref ... has the wrong format` — regex chưa nhận `/`); test query PASS sẵn nhờ Task 1 (giữ làm khoá hành vi).

- [ ] **Step 3: Implement**

Trong `src/center_kb/kbcontext.py` thay `_REF_RE`:

```python
_REF_RE = re.compile(
    r"^(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s+§?(?P<sec>\S+)$"
)
```

(Mỗi segment giữ đúng charset cũ; `/` chỉ là dấu nối segment — không cho segment rỗng/đầu-cuối slash.)

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/test_kbcontext.py tests/test_query.py tests/test_resolve.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/kbcontext.py tests/test_kbcontext.py tests/test_query.py
git commit -m "feat: refs accept nested repo qualifier mid/repo-x:doc-id"
```

---

### Task 3: `_snapshot_federation` + tham số `snapshot_fn`

**Files:**
- Modify: `src/center_kb/publish.py` (`_publish_direct`, `_publish_pr` nhận `snapshot_fn`; thêm `_snapshot_federation`, `_FED_TOP_EXCLUDE`)
- Test: `tests/test_publish_hub.py` (mới)

**Interfaces:**
- Consumes: `hashsync.build_manifest(root, exclude)` (exclude khớp relpath posix chính xác), `hashsync.apply_sync`, `federation.build_federation_index` (Task 1), `hub_mod.HubHandle`.
- Produces: `publish._snapshot_federation(fed_src: Path, handle: HubHandle, rid: str, source_commit: str, source_url: str | None = None, store=None) -> tuple[int, bool]` — mirror `fed_src` → `federation/<rid>/` trên hub trên, loại `index.yaml`/`registry.yaml`/`.gitkeep` tầng đỉnh, KHÔNG viết `_meta.yaml` gốc; trả `(n_docs, changed)` với `n_docs` = tổng doc mọi leaf entry nguồn. `_publish_direct(..., snapshot_fn=_snapshot)` / `_publish_pr(..., snapshot_fn=_snapshot)` — mặc định giữ hành vi cũ.

- [ ] **Step 1: Viết test fail**

```python
# tests/test_publish_hub.py
from pathlib import Path

import pytest

from center_kb import publish
from center_kb.hub import HubHandle
from tests.conftest import make_fed_entry


@pytest.fixture
def mid_fed(tmp_path: Path) -> Path:
    """federation/ của hub trung gian: 1 entry phẳng + 1 entry lồng + file tầng đỉnh."""
    fed = tmp_path / "mid" / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    (fed / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (fed / "registry.yaml").write_text("repos: {}\n", encoding="utf-8")
    (fed / ".gitkeep").write_text("", encoding="utf-8")
    return fed


@pytest.fixture
def upper(tmp_path: Path) -> HubHandle:
    root = tmp_path / "root-hub"
    (root / "federation").mkdir(parents=True)
    return HubHandle(root=root)


def test_snapshot_federation_mirrors_entries(mid_fed, upper):
    n_docs, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is True
    assert n_docs == 2
    dest = upper.federation_dir / "mid"
    assert (dest / "repo-a" / "index.yaml").exists()
    assert (dest / "repo-a" / "_meta.yaml").exists()  # _meta của leaf mirror verbatim
    assert (dest / "leaf-hub" / "repo-b" / "doc-b" / "_manifest.yaml").exists()


def test_snapshot_federation_excludes_top_level_files(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    dest = upper.federation_dir / "mid"
    assert not (dest / "index.yaml").exists()      # aggregate index nguồn không đẩy
    assert not (dest / "registry.yaml").exists()
    assert not (dest / ".gitkeep").exists()
    assert not (dest / "_meta.yaml").exists()      # không viết meta gốc


def test_snapshot_federation_noop_when_unchanged(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    n_docs, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is False
    assert n_docs == 2


def test_snapshot_federation_applies_deletions(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    import shutil

    shutil.rmtree(mid_fed / "repo-a")
    _, changed = publish._snapshot_federation(mid_fed, upper, "mid", "abc1235")
    assert changed is True
    assert not (upper.federation_dir / "mid" / "repo-a").exists()


def test_snapshot_federation_rejects_escaping_rid(mid_fed, upper):
    with pytest.raises(publish.PublishError):
        publish._snapshot_federation(mid_fed, upper, "../evil", "abc1234")
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_publish_hub.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.publish' has no attribute '_snapshot_federation'`

- [ ] **Step 3: Implement**

Trong `src/center_kb/publish.py`:

Thêm sau `_snapshot`:

```python
_FED_TOP_EXCLUDE = ("index.yaml", "registry.yaml", ".gitkeep")


def _snapshot_federation(
    fed_src: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    source_url: str | None = None,
    store=None,
) -> tuple[int, bool]:
    """Sync federation/ (hub trung gian) → federation/<rid>/ trên hub cấp trên.

    Khác _snapshot: nguồn là cả cây federation (leaf entries lồng nhau, mỗi leaf
    tự mang _meta.yaml); index.yaml/registry.yaml tầng đỉnh là sản phẩm riêng
    của hub nguồn — không đẩy; KHÔNG viết _meta.yaml ở gốc đích (gốc entry hub
    là namespace, không phải leaf — walk đệ quy phải đi xuyên qua nó).
    Assets (kể cả record S3-divert _assets.yaml) mirror verbatim.
    """
    from center_kb import hashsync

    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    n_docs = len(federation.build_federation_index(fed_src).docs)
    src_man = hashsync.build_manifest(fed_src, exclude=_FED_TOP_EXCLUDE)
    dest_man = hashsync.build_manifest(dest)
    changed, deleted = hashsync.diff_manifests(src_man, dest_man)
    if not changed and not deleted:
        return n_docs, False
    hashsync.apply_sync(fed_src, dest, changed, deleted)
    return n_docs, True
```

Sửa signature `_publish_direct` và `_publish_pr` (mặc định giữ hành vi cũ), và mọi lời gọi `_snapshot(...)` bên trong hai hàm đó thành `snapshot_fn(...)`:

```python
def _publish_direct(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    max_retries: int,
    snapshot_fn=_snapshot,
) -> PublishReport:
    n_docs, changed = snapshot_fn(kb_abs, handle, rid, source_commit)
    ...  # phần còn lại giữ nguyên


def _publish_pr(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    snapshot_fn=_snapshot,
) -> PublishReport:
    ...
        n_docs, changed = snapshot_fn(kb_abs, handle, rid, source_commit)
    ...  # phần còn lại giữ nguyên
```

- [ ] **Step 4: Chạy test pass + regression publish**

Run: `pytest tests/test_publish_hub.py tests/test_publish.py tests/test_intake_publish.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py tests/test_publish_hub.py
git commit -m "feat: federation snapshot for hub-to-hub publish (snapshot_fn seam)"
```

---

### Task 4: Cycle guard

**Files:**
- Modify: `src/center_kb/federation.py` (thêm `find_cycle_segment`)
- Test: `tests/test_publish_hub.py` (thêm test)

**Interfaces:**
- Consumes: `iter_entry_dirs` (Task 1).
- Produces: `federation.find_cycle_segment(federation_dir: Path, forbidden: set[str]) -> str | None` — path-id đầu tiên chứa một segment nằm trong `forbidden`, `None` nếu sạch. Task 5 gọi với `forbidden = {rid nguồn, repo_id của hub đích (nếu khai báo)}`.

- [ ] **Step 1: Viết test fail**

Thêm vào `tests/test_publish_hub.py`:

```python
def test_find_cycle_segment_detects_own_id(tmp_path):
    from center_kb import federation
    from tests.conftest import make_fed_entry

    fed = tmp_path / "federation"
    make_fed_entry(fed / "root-hub" / "mid", "repo-a", "doc-a")  # nội dung đã quay vòng
    assert federation.find_cycle_segment(fed, {"mid"}) == "root-hub/mid/repo-a"


def test_find_cycle_segment_clean(tmp_path):
    from center_kb import federation
    from tests.conftest import make_fed_entry

    fed = tmp_path / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    assert federation.find_cycle_segment(fed, {"mid"}) is None
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_publish_hub.py::test_find_cycle_segment_detects_own_id -v`
Expected: FAIL — `AttributeError: ... no attribute 'find_cycle_segment'`

- [ ] **Step 3: Implement**

Thêm vào `src/center_kb/federation.py` (sau `iter_entry_dirs`):

```python
def find_cycle_segment(federation_dir: Path, forbidden: set[str]) -> str | None:
    """Path-id entry đầu tiên chứa một segment bị cấm — dấu hiệu nội dung đã
    đi vòng qua hub đó quay lại; publish tiếp sẽ tạo vòng lặp phình vô hạn."""
    for path_id, _ in iter_entry_dirs(federation_dir):
        if any(seg in forbidden for seg in path_id.split("/")):
            return path_id
    return None
```

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/test_publish_hub.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/federation.py tests/test_publish_hub.py
git commit -m "feat: find_cycle_segment — detect federation content looping back"
```

---

### Task 5: `publish_federation()` + CLI dispatch theo kind

**Files:**
- Modify: `src/center_kb/publish.py` (thêm `publish_federation`)
- Modify: `src/center_kb/cli.py:702-769` (lệnh `publish`: dispatch hub-kind trước nhánh intake; tách helper `_echo_publish_report`)
- Test: `tests/test_publish_hub.py` (thêm test), `tests/test_cli_hub.py` (thêm test CLI)

**Interfaces:**
- Consumes: `_snapshot_federation`, `_publish_direct`/`_publish_pr` với `snapshot_fn` (Task 3), `find_cycle_segment` (Task 4), `config.load_config`, `gitio` (`git_root`, `head_commit`, `has_remote`, `remote_url`), `ghio.gh_available`.
- Produces: `publish.publish_federation(kb_dir: Path, hub_ref: str, repo_id: str | None = None, max_retries: int = 3, mode: str = "auto") -> PublishReport`. CLI: `kb publish` trên repo `kind: hub` có `hub:` → đẩy federation; `kind: hub` không `hub:` → exit 1 với thông báo root-hub; kind khác → hành vi cũ nguyên vẹn.

- [ ] **Step 1: Viết test fail (publish_federation)**

Thêm vào `tests/test_publish_hub.py`:

```python
import yaml


def _git_repo(run_git, root: Path) -> None:
    run_git(root, "init")
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@test.local")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")


@pytest.fixture
def mid_hub(tmp_path: Path, run_git) -> Path:
    """Hub trung gian (git repo): .kb/ + federation/ có 2 entry."""
    root = tmp_path / "mid"
    (root / ".kb").mkdir(parents=True)
    fed = root / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: mid\n", encoding="utf-8"
    )
    (root / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git_repo(run_git, root)
    return root


@pytest.fixture
def root_hub(tmp_path: Path, run_git) -> Path:
    root = tmp_path / "root-hub"
    (root / ".kb").mkdir(parents=True)
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: root-hub\n", encoding="utf-8"
    )
    (root / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root / "federation").mkdir()
    (root / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root)
    return root


def test_publish_federation_direct_end_to_end(mid_hub, root_hub):
    report = publish.publish_federation(
        mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
    )
    assert report.repo_id == "mid"
    assert report.n_docs == 2
    fed = root_hub / "federation"
    assert (fed / "mid" / "repo-a" / "index.yaml").exists()
    assert (fed / "mid" / "leaf-hub" / "repo-b" / "index.yaml").exists()
    # aggregate index trên root chứa id lồng
    idx = yaml.safe_load((fed / "index.yaml").read_text(encoding="utf-8"))
    rids = {d["repo_id"] for d in idx["docs"]}
    assert rids == {"mid/repo-a", "mid/leaf-hub/repo-b"}


def test_publish_federation_second_run_noop(mid_hub, root_hub):
    publish.publish_federation(mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct")
    report = publish.publish_federation(
        mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
    )
    assert report.n_docs == 2  # no-op, không lỗi


def test_publish_federation_rejects_self_hub(mid_hub):
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(mid_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_rejects_own_id_in_entries(mid_hub, root_hub):
    # nội dung của 'mid' đã quay vòng về federation của chính nó
    make_fed_entry(mid_hub / "federation" / "upper" / "mid", "repo-c", "doc-c")
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_rejects_dest_id_in_entries(mid_hub, root_hub):
    # federation của mid chứa entry đến từ root-hub → đẩy lên root-hub là trả ngược
    make_fed_entry(mid_hub / "federation" / "root-hub", "repo-d", "doc-d")
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_missing_federation_dir(tmp_path, run_git, root_hub):
    bare = tmp_path / "bare"
    (bare / ".kb").mkdir(parents=True)
    (bare / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git_repo(run_git, bare)
    with pytest.raises(publish.PublishError, match="no federation"):
        publish.publish_federation(bare / ".kb", str(root_hub), repo_id="bare", mode="direct")
```

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_publish_hub.py -v -k publish_federation`
Expected: FAIL — `AttributeError: ... no attribute 'publish_federation'`

- [ ] **Step 3: Implement `publish_federation`**

Thêm vào `src/center_kb/publish.py` (sau `publish`):

```python
def publish_federation(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
) -> PublishReport:
    """Hub trung gian đẩy federation/ của nó lên hub cấp trên.

    Chỉ federation/ được đẩy — .kb/ riêng của hub là bàn soạn thảo, muốn share
    thì self-publish vào chính nó trước. Cycle guard chạy trước khi ghi byte nào.
    """
    from center_kb import config as config_mod

    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    fed_src = source_root / "federation"
    if not fed_src.is_dir():
        raise PublishError(
            "this hub has no federation/ directory — nothing to publish upstream"
        )
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise PublishError(
            f"repo-id '{rid}' is invalid — only letters/digits/._- allowed, no path separators"
        )
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{gitio.redact_url(hub_ref)}'")
    if handle.root.resolve() == source_root.resolve():
        raise PublishError(
            "federation cycle detected: the upstream hub resolves to this repo itself"
        )
    forbidden = {rid}
    dest_rid = config_mod.load_config(handle.kb_dir).repo_id
    if dest_rid:
        forbidden.add(dest_rid)
    hit = federation.find_cycle_segment(fed_src, forbidden)
    if hit is not None:
        raise PublishError(
            f"federation cycle detected: entry '{hit}' contains a hub id from this "
            "publish chain — publishing would loop content back on itself"
        )
    _neutralize_excludes(handle.root)
    if mode == "auto":
        use_pr = (
            gitio.has_remote(handle.root)
            and "github" in gitio.remote_url(handle.root)
            and ghio.gh_available()
        )
        mode = "pr" if use_pr else "direct"
    if mode == "pr":
        return _publish_pr(
            fed_src, handle, rid, source_commit, snapshot_fn=_snapshot_federation
        )
    return _publish_direct(
        fed_src, handle, rid, source_commit, max_retries,
        snapshot_fn=_snapshot_federation,
    )
```

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/test_publish_hub.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 5: Viết test fail (CLI dispatch)**

Thêm vào cuối `tests/test_cli_hub.py` (dùng đúng runner pattern sẵn có trong file — `CliRunner` + `app` import từ `center_kb.cli`; nếu file dùng helper khác, theo pattern của file):

```python
def test_cli_publish_hub_kind_dispatches_federation(tmp_path, run_git, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.conftest import make_fed_entry
    from tests.test_publish_hub import _git_repo

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8"
    )
    _git_repo(run_git, mid)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root_hub / "federation" / "mid" / "repo-a" / "index.yaml").exists()


def test_cli_publish_root_hub_without_upstream_errors(tmp_path, run_git):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    _git_repo(run_git, root_hub)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(root_hub / ".kb")])
    assert result.exit_code == 1
    assert "root hub" in result.output
```

Run: `pytest tests/test_cli_hub.py -k "hub_kind or root_hub_without" -v`
Expected: FAIL — hub-kind hiện đi đường publish `.kb/` thường (root-hub test fail vì require_hub ra guide chung, exit message không chứa "root hub"; dispatch test fail vì mirror `.kb/` chứ không phải `federation/`).

- [ ] **Step 6: Implement CLI dispatch**

Trong `src/center_kb/cli.py`, lệnh `publish` (dòng ~702): thêm helper module-level (đặt ngay trên `def publish`):

```python
def _echo_publish_report(report) -> None:
    if report.mode == "pr":
        if report.pr_url:
            typer.echo(
                f"kb publish: {report.repo_id} @ {report.source_commit} — "
                f"{report.n_docs} doc, PR: {report.pr_url}"
            )
            typer.echo("Content goes live when the PR is merged on the hub.")
        else:
            typer.echo("kb publish: nothing changed — no PR needed.")
        return
    action = "push" if report.pushed else "commit only (hub has no remote)"
    typer.echo(
        f"kb publish: {report.repo_id} @ {report.source_commit} — "
        f"{report.n_docs} doc, {action}."
    )
```

Trong thân `publish`, ngay sau `cfg = load_config(kb_dir)` và TRƯỚC nhánh `if cfg.intake ...`, chèn (chuyển dòng `mode = ...` lên trước nhánh này):

```python
    mode = "pr" if pr else "direct" if direct else "auto"
    if cfg.kind == "hub":
        try:
            hub_ref = require_hub(hub, kb_dir)
        except HubConfigError:
            typer.secho(
                "this is a root hub (kind: hub, no `hub:` configured) — nothing "
                "to publish upstream; add `hub: <url|path>` to .kb/config.yaml "
                "to chain it to a higher hub",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        try:
            report = publish_mod.publish_federation(
                kb_dir, hub_ref,
                repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
            )
        except (publish_mod.PublishError, gitio.GitError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            raise typer.Exit(1)
        _echo_publish_report(report)
        return
```

Phần cuối hàm (2 khối echo cũ cho child) thay bằng một lời gọi `_echo_publish_report(report)` — xoá code echo trùng lặp.

- [ ] **Step 7: Chạy test pass + regression CLI**

Run: `pytest tests/test_cli_hub.py tests/test_cli.py tests/test_publish.py tests/test_publish_hub.py tests/test_publish_intake_cli.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/publish.py src/center_kb/cli.py tests/test_publish_hub.py tests/test_cli_hub.py
git commit -m "feat: kb publish on hub-kind pushes federation/ upstream with cycle guard"
```

---

### Task 6: Doctor — health cho hub phân tầng

**Files:**
- Modify: `src/center_kb/doctor.py` (thêm `check_federation_publish`, `_fed_tree_digest`, `_ENTRY_SEGMENT_RE`)
- Modify: `src/center_kb/cli.py:1211-1259` (lệnh `doctor`: kind-aware)
- Test: `tests/test_doctor_hubkind.py` (mới)

**Interfaces:**
- Consumes: `federation.iter_entry_dirs`, `find_cycle_segment` (Task 1/4), `HubHandle`, `config.load_config`, `gitio.git_root`.
- Produces: `doctor.check_federation_publish(source_root: Path, handle: HubHandle | None, repo_id: str | None) -> list[Issue]` — (a) error khi path-id entry có segment không hợp lệ; (b) warning khi `repo_id` của chính mình xuất hiện trong entry (cycle sắp xảy ra); (c) warning chưa publish lên upstream / snapshot upstream lệch digest. CLI doctor: kind `hub` → gọi thêm hàm này, và `check_hub(..., repo_id=None)` (bỏ so digest `.kb/` — hub không publish `.kb/`).

- [ ] **Step 1: Viết test fail**

```python
# tests/test_doctor_hubkind.py
from pathlib import Path

from center_kb import doctor
from center_kb.hub import HubHandle
from tests.conftest import make_fed_entry


def _mid(tmp_path: Path) -> Path:
    root = tmp_path / "mid"
    make_fed_entry(root / "federation", "repo-a", "doc-a")
    return root


def test_check_federation_publish_clean_not_published_yet(tmp_path):
    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    issues = doctor.check_federation_publish(root, HubHandle(root=upper), "mid")
    assert [i.level for i in issues] == ["warning"]
    assert "not published" in issues[0].message


def test_check_federation_publish_digest_match_no_issue(tmp_path):
    from center_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    assert doctor.check_federation_publish(root, handle, "mid") == []


def test_check_federation_publish_digest_drift_warns(tmp_path):
    from center_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    make_fed_entry(root / "federation", "repo-new", "doc-new")
    issues = doctor.check_federation_publish(root, handle, "mid")
    assert any("differs from the published snapshot" in i.message for i in issues)


def test_check_federation_publish_warns_on_cycle(tmp_path):
    root = _mid(tmp_path)
    make_fed_entry(root / "federation" / "upper" / "mid", "repo-c", "doc-c")
    issues = doctor.check_federation_publish(root, None, "mid")
    assert any("cycle" in i.message for i in issues)


def test_check_federation_publish_invalid_segment_errors(tmp_path):
    root = _mid(tmp_path)
    make_fed_entry(root / "federation", "-bad-name", "doc-z")
    issues = doctor.check_federation_publish(root, None, "mid")
    assert any(i.level == "error" and "-bad-name" in i.message for i in issues)
```

(Entry tên bắt đầu bằng `-` không khớp charset segment `[A-Za-z0-9][A-Za-z0-9._-]*` → error.)

- [ ] **Step 2: Chạy test — phải fail**

Run: `pytest tests/test_doctor_hubkind.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.doctor' has no attribute 'check_federation_publish'`

- [ ] **Step 3: Implement**

Thêm vào `src/center_kb/doctor.py` (sau `check_hub`; thêm `import re` đầu file):

```python
_ENTRY_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_FED_TOP_SKIP = {"index.yaml", "registry.yaml", ".gitkeep"}


def _fed_tree_digest(root: Path) -> str:
    """Digest deterministic của một cây federation — bỏ file tầng đỉnh mà
    publish không mirror (index/registry/.gitkeep) và mọi _meta.yaml
    (giống _kb_tree_digest: snapshot-only, hai phía đều bỏ nên so sánh vẫn đúng)."""
    import hashlib

    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        rel = path.relative_to(root).as_posix()
        if rel in _FED_TOP_SKIP:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def check_federation_publish(
    source_root: Path, handle: "HubHandle | None", repo_id: str | None
) -> list[Issue]:
    """Health hub phân tầng: id entry hợp lệ, cảnh báo cycle, trạng thái đã
    publish lên upstream. handle = hub CẤP TRÊN (None khi root hub / offline)."""
    from center_kb.federation import find_cycle_segment, iter_entry_dirs

    fed_src = source_root / "federation"
    issues: list[Issue] = []
    for path_id, _ in iter_entry_dirs(fed_src):
        if not all(_ENTRY_SEGMENT_RE.fullmatch(s) for s in path_id.split("/")):
            issues.append(
                Issue(
                    "error",
                    f"federation entry '{path_id}' has an invalid path segment — "
                    "only letters/digits/._- per segment",
                )
            )
    if repo_id:
        hit = find_cycle_segment(fed_src, {repo_id})
        if hit is not None:
            issues.append(
                Issue(
                    "warning",
                    f"own repo id '{repo_id}' appears inside federation entry "
                    f"'{hit}' — content has looped back; `kb publish` will refuse",
                )
            )
    if handle is not None and repo_id:
        dest = handle.federation_dir / repo_id
        if not dest.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"hub '{repo_id}' has not published to the upstream hub yet — "
                    "run `kb publish`",
                )
            )
        elif _fed_tree_digest(fed_src) != _fed_tree_digest(dest):
            issues.append(
                Issue(
                    "warning",
                    f"local federation/ differs from the published snapshot "
                    f"federation/{repo_id} on the upstream hub — run `kb publish`",
                )
            )
    return issues
```

- [ ] **Step 4: Chạy test pass**

Run: `pytest tests/test_doctor_hubkind.py -q`
Expected: PASS.

- [ ] **Step 5: Nối vào CLI doctor**

Trong `src/center_kb/cli.py` lệnh `doctor` (dòng ~1211): import thêm `check_federation_publish` và `load_config`; sau khi có `repo_id` và trước `check_hub(...)`, thay khối gọi `check_hub` bằng:

```python
    cfg_kind = ""
    try:
        from center_kb.config import load_config as _load_config

        cfg_kind = _load_config(kb_dir).kind
    except Exception:  # config hỏng đã được check_kind báo
        pass
    if cfg_kind == "hub":
        from center_kb import gitio as _gitio2
        from center_kb.doctor import check_federation_publish

        source_root = _gitio2.git_root(kb_dir.resolve())
        upstream = handle if (handle and handle.root.resolve() != source_root.resolve()) else None
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=None)
        issues += hub_issues
        issues += check_federation_publish(source_root, upstream, repo_id)
    else:
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_id)
        issues += hub_issues
```

(Hub-kind: bỏ so digest `.kb/` trong `check_hub` — hub không publish `.kb/` của nó dưới tên `repo_id`; `upstream=None` khi hub tự trỏ chính nó — root hub soi chính mình thì không có "upstream" để so.)

- [ ] **Step 6: Chạy toàn bộ doctor tests**

Run: `pytest tests/test_doctor_hubkind.py tests/test_doctor.py tests/test_doctor_hub.py tests/test_cli_doctor_diff.py -q`
Expected: PASS toàn bộ.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/doctor.py src/center_kb/cli.py tests/test_doctor_hubkind.py
git commit -m "feat: kb doctor checks multi-tier hub health (nested ids, cycle, upstream drift)"
```

---

### Task 7: Demo 3 tầng + gate regression + README

**Files:**
- Modify: `scripts/demo-federation.sh` (thêm tầng mid + cycle demo)
- Modify: `README.md` (mục 7.9 — thêm đoạn multi-tier)

**Interfaces:**
- Consumes: toàn bộ Task 1–6 qua CLI `kb publish` / `kb query`.

- [ ] **Step 1: Mở rộng demo script**

Trong `scripts/demo-federation.sh`, sau bước 8 hiện tại (trước dòng echo "Demo complete"), thêm:

```bash
echo "== 9. Multi-tier: root hub + mid hub =="
ROOT_HUB="$DEMO_DIR/kb-root-hub"
mkdir -p "$ROOT_HUB/.kb" "$ROOT_HUB/federation"
printf 'docs: []\n' > "$ROOT_HUB/.kb/index.yaml"
printf 'kind: hub\nrepo_id: root-hub\n' > "$ROOT_HUB/.kb/config.yaml"
touch "$ROOT_HUB/federation/.gitkeep"
git init -q "$ROOT_HUB"; G "$ROOT_HUB" add -A; G "$ROOT_HUB" commit -qm "root hub v0"

# Biến hub cũ thành hub trung gian: khai kind + upstream
printf 'kind: hub\nrepo_id: mid\nhub: %s\n' "$ROOT_HUB" > "$HUB/.kb/config.yaml"
git init -q "$HUB" 2>/dev/null || true
G "$HUB" add -A; G "$HUB" commit -qm "mid hub config" || true

echo "== 10. Mid hub publishes its federation upstream =="
kb publish --kb-dir "$HUB/.kb"
echo "-- aggregate index on the ROOT hub (nested ids mid/...):"
cat "$ROOT_HUB/federation/index.yaml"

echo "== 11. Query at the root sees every tier =="
kb query "beta gadget" --hub "$ROOT_HUB" --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 12. Cycle demo: root hub pointed back at mid → publish refuses =="
printf 'kind: hub\nrepo_id: root-hub\nhub: %s\n' "$HUB" > "$ROOT_HUB/.kb/config.yaml"
G "$ROOT_HUB" add -A; G "$ROOT_HUB" commit -qm "misconfigure: point back at mid"
if kb publish --kb-dir "$ROOT_HUB/.kb" 2>&1 | grep -q "federation cycle detected"; then
  echo "-- cycle correctly refused"
else
  echo "-- ERROR: cycle was NOT refused" && exit 1
fi
```

Lưu ý: hub gốc trong demo (`$HUB`) đã là git repo từ bước 1 — dòng `git init ... || true` chỉ phòng hờ; publish của mid chạy direct mode vì `$ROOT_HUB` là local path. Bước 11 cite dạng `mid/repo-beta:beta-spec §2.1`.

- [ ] **Step 2: Chạy demo end-to-end**

Run: `bash scripts/demo-federation.sh`
Expected: chạy hết, in "cycle correctly refused", exit 0. Nếu bước 11 không ra kết quả — kiểm tra search.db của root hub cache (CENTER_KB_HUB_CACHE trong demo đã cô lập).

- [ ] **Step 3: README — mục 7.9 thêm đoạn multi-tier**

Trong `README.md`, cuối mục `7.9` (Phase 3 — federation & remote MCP), thêm:

```markdown
**Multi-tier federation (hub → hub):** a `kind: hub` repo may itself declare
`hub:` + `repo_id:` in `.kb/config.yaml` — `kb publish` on such a repo mirrors
its **`federation/`** (not its own `.kb/`) into `federation/<hub-id>/` on the
upstream hub, keeping the nested layout (`federation/mid/repo-x/…`). Depth is
unbounded; entry ids become paths (`mid/repo-x:doc-id` when qualifying refs).
Publishing refuses with `federation cycle detected` when the chain would loop
content back (upstream resolves to itself, or an entry path already contains a
hub id from the chain). A hub without `hub:` is a root hub — `kb publish` there
errors with guidance. Scope search by choosing which hub you query: a team hub
returns the team's knowledge, the root hub returns everything.
```

- [ ] **Step 4: Full test suite + gate regression**

Run: `pytest tests/ -q && pytest tests-gate/regression -q`
Expected: PASS toàn bộ, không sửa fixture nào của gate. (Gate e2e/journey chạy CI, không bắt buộc local.)

- [ ] **Step 5: Commit**

```bash
git add scripts/demo-federation.sh README.md
git commit -m "docs: 3-tier federation demo + README multi-tier section"
```
