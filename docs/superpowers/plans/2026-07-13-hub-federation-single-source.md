# Hub Federation = Single Source of Truth — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb query` + toàn bộ MCP tool + Web UI chỉ đọc từ `federation/` của hub; `.kb/` local thuần soạn thảo; publish (mirror L0→L3, qua PR trên hub) là đường duy nhất vào federation; index tổng `federation/index.yaml` sinh deterministic.

**Architecture:** `federation/<repo-id>/` là copy nguyên trạng một `.kb/` nên toàn bộ code đọc hiện có tái dùng bằng cách đổi gốc trỏ. Tầng mới dưới đáy: `config.py` (hub từ `.kb/config.yaml`) và `ghio.py` (wrapper `gh`). Mọi consumer (query/kbcontext/resolve/doctor/mcp/cli/web) chuyển từ `kb_dir` sang `HubHandle`.

**Tech Stack:** Python 3.13 (venv `.venv/`), pydantic, typer, FastMCP (mcp>=1.2), rank-bm25, sqlite-vec/fastembed (optional), pytest, git CLI, GitHub CLI (`gh`, chỉ PR mode).

**Spec:** `docs/superpowers/specs/2026-07-13-hub-federation-single-source-design.md`

## Global Constraints

- **Federation-only tuyệt đối:** không còn đường đọc nào vào `.kb/` local hay `.kb/` của hub khi query/get/context/resolve — không có cờ `--local`.
- **Ưu tiên cấu hình hub:** `--hub` flag > env `CENTER_KB_HUB` > `.kb/config.yaml`. Thiếu cả ba → lỗi đúng chuỗi `config.HUB_GUIDE`.
- **Index tổng deterministic:** `build_federation_index()` chỉ phụ thuộc nội dung `federation/*/`; chạy 2 lần cho kết quả bằng nhau tuyệt đối.
- **kb-context:** pin đúng 1 commit = HEAD của hub; refs luôn dạng `repo:doc §sec`; parser vẫn đọc block cũ có `hub_version` (không sản sinh mới).
- **`status: reviewed`:** không sản sinh mới, không có lệnh tạo ra nó, nhưng `SectionEntry` PHẢI tiếp tục parse được manifest cũ chứa `reviewed` — giữ nguyên Literal trong models.
- **Entry federation format cũ (`manifests/`):** skip + warning "old slim layout … republish", không bao giờ crash.
- **Test hermetic:** không network, không gọi `claude`/`copilot`/`gh` thật (máy dev CÓ các CLI này — phải monkeypatch), hub luôn là local path trong tmp dir, git fixtures dùng fixture `run_git` (đã chống `excludesFile` global).
- **Chạy test bằng:** `.venv/bin/python -m pytest <file> -q`. Lint: `.venv/bin/python -m ruff check src tests`. Type: `.venv/bin/python -m mypy src`.
- **Branch:** làm trên branch `feat/hub-federation-single-source` (tạo ở Task 1, Step 0).
- **Suite đỏ có kiểm soát:** từ Task 3 đến hết Task 14, full suite được phép đỏ ở những file test CHƯA đến lượt chuyển đổi; mỗi task phải xanh toàn bộ file test nêu trong task đó. Task 15 bắt buộc full suite + ruff + mypy xanh.

## Bản đồ file

| Hành động | File |
|---|---|
| Create | `src/center_kb/config.py`, `src/center_kb/ghio.py`, `src/center_kb/templates/init/config.yaml`, `tests/test_config.py`, `tests/test_ghio.py`, `tests/test_federation_e2e.py` |
| Rewrite | `src/center_kb/federation.py`, `src/center_kb/publish.py`, `src/center_kb/query.py`, `src/center_kb/resolve.py` (nửa dưới), `src/center_kb/web/api.py`, `scripts/demo-federation.sh`, `src/center_kb/templates/init/claude-skill-kb-publish.md`, `src/center_kb/templates/init/copilot-kb-publish.prompt.md`, `.github/workflows/kb-publish.yml` + template cùng tên |
| Modify | `src/center_kb/models.py`, `src/center_kb/gitio.py`, `src/center_kb/kbcontext.py`, `src/center_kb/doctor.py`, `src/center_kb/mcp.py`, `src/center_kb/cli.py`, `src/center_kb/initcmd.py`, `src/center_kb/web/ui.py`, `tests/conftest.py`, `README.md`, `pyproject.toml`, `src/center_kb/templates/init/QUICKSTART.md` |
| Delete | `src/center_kb/review.py`, `.github/workflows/kb-review.yml`, `src/center_kb/templates/init/kb-review.yml`, `tests/test_review.py`, `tests/test_cli_approve.py`, `tests/test_query_hub.py`, `tests/test_resolve_hub.py`, `tests/test_phase2_e2e.py`, `tests/test_phase3_e2e.py` |

**Không đổi:** `hub.py` (resolve/cache/TTL giữ nguyên), `embed.py` (ensure_index/semantic_search nhận `kb_dir` + `db_path` bất kỳ — chỉ caller đổi), `ingest/*`, `summarize.py`, `build.py` (trừ 1 khối nhỏ ở Task 11), `diff.py`, `web/auth.py`, `web/mdrender.py`.

---

### Task 1: `config.py` — hub bắt buộc từ config/flag/env

**Files:**
- Create: `src/center_kb/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `models.load_yaml_model`
- Produces: `KBConfig(BaseModel)` {hub: str = "", repo_id: str = ""}; `load_config(kb_dir: Path) -> KBConfig`; `require_hub(cli_value: str, kb_dir: Path) -> str` (raise `HubConfigError`); `effective_repo_id(cli_value: str, kb_dir: Path) -> str | None`; hằng `CONFIG_NAME = "config.yaml"`, `HUB_GUIDE`. Task 10/11/13 gọi các hàm này.

- [ ] **Step 0: Tạo branch**

```bash
git checkout -b feat/hub-federation-single-source
```

- [ ] **Step 1: Viết test fail**

Tạo `tests/test_config.py`:

```python
from pathlib import Path

import pytest

from center_kb.config import (
    HUB_GUIDE,
    HubConfigError,
    KBConfig,
    effective_repo_id,
    load_config,
    require_hub,
)


def _kb(tmp_path: Path, text: str | None = None) -> Path:
    kb = tmp_path / ".kb"
    kb.mkdir()
    if text is not None:
        (kb / "config.yaml").write_text(text, encoding="utf-8")
    return kb


def test_load_config_missing_file_returns_defaults(tmp_path):
    assert load_config(_kb(tmp_path)) == KBConfig()


def test_load_config_reads_hub_and_repo_id(tmp_path):
    kb = _kb(tmp_path, "hub: /srv/kb-hub\nrepo_id: my-kb\n")
    cfg = load_config(kb)
    assert cfg.hub == "/srv/kb-hub"
    assert cfg.repo_id == "my-kb"


def test_require_hub_prefers_cli_value(tmp_path):
    kb = _kb(tmp_path, "hub: /from-config\n")
    assert require_hub("/from-flag", kb) == "/from-flag"


def test_require_hub_falls_back_to_config(tmp_path):
    kb = _kb(tmp_path, "hub: /from-config\n")
    assert require_hub("", kb) == "/from-config"


def test_require_hub_raises_with_guide_when_unconfigured(tmp_path):
    with pytest.raises(HubConfigError) as exc:
        require_hub("", _kb(tmp_path))
    assert str(exc.value) == HUB_GUIDE


def test_effective_repo_id_priority_and_none(tmp_path):
    kb = _kb(tmp_path, "repo_id: cfg-id\n")
    assert effective_repo_id("cli-id", kb) == "cli-id"
    assert effective_repo_id("", kb) == "cfg-id"
    assert effective_repo_id("", _kb(tmp_path / "other")) is None
```

Lưu ý: `_kb(tmp_path / "other")` cần mkdir parents — sửa `_kb` dùng `kb.mkdir(parents=True)`.

- [ ] **Step 2: Chạy test — phải FAIL**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: FAIL `ModuleNotFoundError: No module named 'center_kb.config'`

- [ ] **Step 3: Implement**

Tạo `src/center_kb/config.py`:

```python
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from center_kb import models

CONFIG_NAME = "config.yaml"

HUB_GUIDE = (
    "no hub configured — add `hub: <url|path>` to .kb/config.yaml "
    "(or pass --hub / set CENTER_KB_HUB)"
)


class HubConfigError(RuntimeError):
    """The hub is mandatory (federation is the only read source) but not configured."""


class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""


def load_config(kb_dir: Path) -> KBConfig:
    path = kb_dir / CONFIG_NAME
    if not path.exists():
        return KBConfig()
    return models.load_yaml_model(path, KBConfig)


def require_hub(cli_value: str, kb_dir: Path) -> str:
    """cli_value đã gộp env (typer envvar / mcp parse_args tự fold CENTER_KB_HUB)."""
    hub = cli_value or load_config(kb_dir).hub
    if not hub:
        raise HubConfigError(HUB_GUIDE)
    return hub


def effective_repo_id(cli_value: str, kb_dir: Path) -> str | None:
    return cli_value or load_config(kb_dir).repo_id or None
```

- [ ] **Step 4: Test pass**

Run: `.venv/bin/python -m pytest tests/test_config.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/config.py tests/test_config.py
git commit -m "feat: .kb/config.yaml — mandatory hub config with flag/env/file priority"
```

---

### Task 2: models — `FedIndexEntry` + `FederationIndex`

**Files:**
- Modify: `src/center_kb/models.py` (thêm sau class `KBIndex`)
- Test: `tests/test_models.py` (thêm test, không sửa test cũ)

**Interfaces:**
- Produces: `FedIndexEntry` {repo_id, doc_id, title="", revision="", tags=[], summary="", source_commit="", published_at=""}; `FederationIndex` {docs: list[FedIndexEntry]}. Task 3 build/ghi, Task 9/13 đọc.

- [ ] **Step 1: Viết test fail** — thêm vào cuối `tests/test_models.py`:

```python
def test_federation_index_roundtrip(tmp_path):
    from center_kb.models import (
        FederationIndex,
        FedIndexEntry,
        load_yaml_model,
        save_yaml_model,
    )

    idx = FederationIndex(
        docs=[
            FedIndexEntry(
                repo_id="arinc-kb",
                doc_id="arinc-424",
                title="ARINC 424",
                revision="Supplement 22",
                tags=["arinc424"],
                summary="Nav DB spec.",
                source_commit="abc1234",
                published_at="2026-07-13T00:00:00+00:00",
            )
        ]
    )
    path = tmp_path / "index.yaml"
    save_yaml_model(path, idx)
    loaded = load_yaml_model(path, FederationIndex)
    assert loaded == idx


def test_federation_index_defaults():
    from center_kb.models import FederationIndex, FedIndexEntry

    e = FedIndexEntry(repo_id="r", doc_id="d")
    assert e.tags == [] and e.revision == "" and e.published_at == ""
    assert FederationIndex().docs == []


def test_section_status_still_parses_reviewed():
    from center_kb.models import SectionEntry

    sec = SectionEntry(id="1.1", title="T", file="ch1", status="reviewed")
    assert sec.status == "reviewed"
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_models.py -q` → `ImportError: cannot import name 'FederationIndex'` (test reviewed pass sẵn — giữ làm chốt tương thích).

- [ ] **Step 3: Implement** — thêm vào `src/center_kb/models.py` ngay sau `class KBIndex`:

```python
class FedIndexEntry(BaseModel):
    repo_id: str
    doc_id: str
    title: str = ""
    revision: str = ""
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    source_commit: str = ""
    published_at: str = ""


class FederationIndex(BaseModel):
    docs: list[FedIndexEntry] = Field(default_factory=list)
```

KHÔNG sửa `SectionEntry.status` — Literal giữ nguyên cả ba giá trị (tương thích manifest cũ).

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_models.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/models.py tests/test_models.py
git commit -m "feat: FederationIndex/FedIndexEntry models for the aggregate index"
```

---

### Task 3: `federation.py` — loader layout mirror + index tổng (+ fixtures dùng chung)

**Files:**
- Rewrite: `src/center_kb/federation.py`
- Modify: `tests/conftest.py` (thêm `make_fed_entry` + fixture `fed_hub`; GIỮ các fixture cũ `fixture_kb`, `run_git`, `git_kb`, `hub_worktree`)
- Rewrite: `tests/test_federation.py`

**Interfaces:**
- Consumes: `models.KBIndex/Manifest/FederationIndex`, Task 2.
- Produces: `FederationMeta` (giữ nguyên fields); `FederatedRepo` dataclass {meta, index, **kb_dir: Path**} — **bỏ field `manifests`**; `load_federation(federation_dir) -> list[FederatedRepo]`; `build_federation_index(federation_dir) -> models.FederationIndex`; `write_federation_index(federation_dir) -> Path`; test helper `make_fed_entry(federation_dir, repo_id, doc_id, ...)` + fixture `fed_hub` (hub git repo, 2 repo published: `icao-kb:icao-annex-2 §1.1` từ khóa "airspace designation", `arinc-kb:arinc-424 §5.3` từ khóa "restrictive airspace", đã có `federation/index.yaml`).
- **Hệ quả:** mọi code đang đọc `repo.manifests` (query/api/doctor/resolve cũ) sẽ đỏ cho đến task tương ứng — đúng ô "suite đỏ có kiểm soát".

- [ ] **Step 1: Thêm helper + fixture vào `tests/conftest.py`** (append cuối file):

```python
def make_fed_entry(
    federation_dir: Path,
    repo_id: str,
    doc_id: str,
    *,
    title: str = "",
    tags: list[str] | None = None,
    summary: str = "Doc summary.",
    sec_id: str = "1.1",
    sec_title: str = "Section One",
    sec_summary: str = "Summary of section one.",
    l2: str | None = None,
    l3: str | None = None,
    source_commit: str = "abc1234",
    published_at: str = "2026-07-13T00:00:00+00:00",
) -> Path:
    """Ghi 1 entry federation format mới (mirror .kb đầy đủ L0→L3)."""
    from center_kb.federation import FederationMeta

    entry = federation_dir / repo_id
    doc_dir = entry / doc_id
    doc_dir.mkdir(parents=True)
    body_l2 = l2 if l2 is not None else (
        f"## {sec_id} {sec_title}\n\nCondensed content of {doc_id} {sec_id}.\n"
    )
    body_l3 = l3 if l3 is not None else (
        f"## {sec_id} {sec_title}\n\nVerbatim content of {doc_id} {sec_id}.\n"
    )
    (doc_dir / "ch1.md").write_text(body_l2, encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text(body_l3, encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id=doc_id,
            title=title or doc_id,
            sections=[
                models.SectionEntry(
                    id=sec_id, title=sec_title, summary=sec_summary,
                    status="summarized", file="ch1",
                )
            ],
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id=doc_id, title=title or doc_id, tags=tags or [], summary=summary,
                )
            ]
        ),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id=repo_id, source_commit=source_commit, published_at=published_at,
        ),
    )
    return entry


@pytest.fixture
def fed_hub(tmp_path: Path, run_git) -> Path:
    """Hub git repo: federation/ có 2 repo published (layout mirror) + index tổng."""
    from center_kb.federation import write_federation_index

    hub = tmp_path / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    fed = hub / "federation"
    make_fed_entry(
        fed, "icao-kb", "icao-annex-2",
        tags=["icao", "airspace"],
        sec_id="1.1", sec_title="Airspace Records",
        sec_summary="Airspace record structure: designation, type, level.",
        l2="## 1.1 Airspace Records\n\nCondensed: airspace designation and type fields.\n",
        l3="## 1.1 Airspace Records\n\nFull raw text about airspace designation.\n",
    )
    make_fed_entry(
        fed, "arinc-kb", "arinc-424",
        tags=["arinc424"],
        sec_id="5.3", sec_title="Restrictive Airspace",
        sec_summary="Restrictive airspace: designation, type, multiple code.",
        l2="## 5.3 Restrictive Airspace\n\nCondensed: restrictive airspace designation codes.\n",
        l3="## 5.3 Restrictive Airspace\n\nFull raw restrictive airspace text.\n",
    )
    write_federation_index(fed)
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub
```

- [ ] **Step 2: Rewrite `tests/test_federation.py`** (thay toàn bộ nội dung):

```python
from center_kb import models
from center_kb.federation import (
    build_federation_index,
    load_federation,
    write_federation_index,
)
from tests.conftest import make_fed_entry


def test_load_federation_reads_mirror_entries(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "icao-kb", "icao-annex-2")
    make_fed_entry(fed, "arinc-kb", "arinc-424")
    repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["arinc-kb", "icao-kb"]
    assert repos[0].kb_dir == fed / "arinc-kb"
    assert repos[0].index.docs[0].id == "arinc-424"


def test_load_federation_missing_dir_returns_empty(tmp_path):
    assert load_federation(tmp_path / "nope") == []


def test_load_federation_skips_old_slim_layout(tmp_path, caplog):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "new-kb", "doc-a")
    old = fed / "old-kb"
    (old / "manifests").mkdir(parents=True)
    (old / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (old / "_meta.yaml").write_text(
        "repo_id: old-kb\nsource_commit: abc\n", encoding="utf-8"
    )
    with caplog.at_level("WARNING"):
        repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["new-kb"]
    assert "old slim layout" in caplog.text


def test_load_federation_skips_broken_entry(tmp_path, caplog):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "good-kb", "doc-a")
    bad = fed / "bad-kb"
    bad.mkdir(parents=True)
    (bad / "index.yaml").write_text("docs: []\n", encoding="utf-8")  # thiếu _meta.yaml
    with caplog.at_level("WARNING"):
        repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["good-kb"]


def test_build_federation_index_deterministic_and_sorted(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "icao-kb", "icao-annex-2", tags=["icao"], source_commit="c1")
    make_fed_entry(fed, "arinc-kb", "arinc-424", tags=["arinc424"], source_commit="c2")
    idx1 = build_federation_index(fed)
    idx2 = build_federation_index(fed)
    assert idx1 == idx2
    assert [(e.repo_id, e.doc_id) for e in idx1.docs] == [
        ("arinc-kb", "arinc-424"),
        ("icao-kb", "icao-annex-2"),
    ]
    assert idx1.docs[0].source_commit == "c2"
    assert idx1.docs[0].tags == ["arinc424"]


def test_write_federation_index_saves_and_reloads(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "solo-kb", "doc-a")
    path = write_federation_index(fed)
    assert path == fed / "index.yaml"
    loaded = models.load_yaml_model(path, models.FederationIndex)
    assert loaded.docs[0].repo_id == "solo-kb"


def test_aggregate_index_file_not_treated_as_entry(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "solo-kb", "doc-a")
    write_federation_index(fed)
    assert len(load_federation(fed)) == 1
```

- [ ] **Step 3: FAIL** — `.venv/bin/python -m pytest tests/test_federation.py -q` → lỗi import (`write_federation_index` chưa có) / `FederatedRepo` chưa có `kb_dir`.

- [ ] **Step 4: Rewrite `src/center_kb/federation.py`** (thay toàn bộ):

```python
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from center_kb import models

logger = logging.getLogger("center_kb.federation")

FEDERATION_INDEX_NAME = "index.yaml"


class FederationMeta(BaseModel):
    repo_id: str
    source_url: str = ""
    source_commit: str
    published_at: str = ""


@dataclass
class FederatedRepo:
    meta: FederationMeta
    index: models.KBIndex
    kb_dir: Path  # federation/<repo-id>/ — mirror .kb đầy đủ (L0→L3)


def load_federation(federation_dir: Path) -> list[FederatedRepo]:
    """Đọc mọi entry federation/<repo>/ theo layout mirror mới.

    Entry format cũ (Phase 3, thư mục 'manifests/') và entry hỏng bị skip kèm
    warning — republish từ repo nguồn để nâng cấp.
    """
    if not federation_dir.is_dir():
        return []
    repos: list[FederatedRepo] = []
    for child in sorted(p for p in federation_dir.iterdir() if p.is_dir()):
        if (child / "manifests").is_dir():
            logger.warning(
                "federation/%s uses the old slim layout — skipping; "
                "run `kb publish` from that repo to upgrade it",
                child.name,
            )
            continue
        meta_path = child / "_meta.yaml"
        index_path = child / "index.yaml"
        if not meta_path.exists() or not index_path.exists():
            logger.warning(
                "federation/%s missing _meta.yaml or index.yaml — skipping", child.name
            )
            continue
        try:
            meta = models.load_yaml_model(meta_path, FederationMeta)
            index = models.load_yaml_model(index_path, models.KBIndex)
        except (yaml.YAMLError, ValidationError) as exc:
            logger.warning("federation/%s is broken — skipping: %s", child.name, exc)
            continue
        repos.append(FederatedRepo(meta=meta, index=index, kb_dir=child))
    return repos


def build_federation_index(federation_dir: Path) -> models.FederationIndex:
    """Index tổng — deterministic 100% từ các snapshot con.

    Thứ tự: repo_id tăng dần (load_federation đã sort), docs theo thứ tự
    index gốc của từng repo.
    """
    entries: list[models.FedIndexEntry] = []
    for repo in load_federation(federation_dir):
        for doc in repo.index.docs:
            entries.append(
                models.FedIndexEntry(
                    repo_id=repo.meta.repo_id,
                    doc_id=doc.id,
                    title=doc.title,
                    revision=doc.revision,
                    tags=doc.tags,
                    summary=doc.summary,
                    source_commit=repo.meta.source_commit,
                    published_at=repo.meta.published_at,
                )
            )
    return models.FederationIndex(docs=entries)


def write_federation_index(federation_dir: Path) -> Path:
    index_path = federation_dir / FEDERATION_INDEX_NAME
    models.save_yaml_model(index_path, build_federation_index(federation_dir))
    return index_path
```

- [ ] **Step 5: PASS** — `.venv/bin/python -m pytest tests/test_federation.py tests/test_config.py tests/test_models.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/federation.py tests/test_federation.py tests/conftest.py
git commit -m "feat: federation mirror layout loader + deterministic aggregate index"
```

---

### Task 4: `gitio` branch helpers + `ghio.py` (wrapper `gh`)

**Files:**
- Modify: `src/center_kb/gitio.py` (thêm 4 hàm cuối file)
- Create: `src/center_kb/ghio.py`
- Test: `tests/test_gitio.py` (thêm), `tests/test_ghio.py` (mới)

**Interfaces:**
- Produces (gitio): `current_branch(root) -> str`; `checkout_branch(root, name, start_point)` (`git checkout -B`); `checkout(root, name)`; `push_branch(root, branch)` (`git push --force origin <branch>`).
- Produces (ghio): `GHError(RuntimeError)`; `gh_available() -> bool`; `pr_url_for_branch(root, branch) -> str` ('' nếu chưa có PR); `create_pr(root, branch, title, body) -> str`; nội bộ `_run_gh(root, *args)` — điểm monkeypatch duy nhất cho test.
- Task 5 (publish PR mode) gọi tất cả các hàm trên.

- [ ] **Step 1: Viết test fail** — thêm vào cuối `tests/test_gitio.py`:

```python
def test_branch_helpers_roundtrip(tmp_path, run_git):
    from center_kb import gitio

    root = tmp_path / "repo"
    root.mkdir()
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    main = gitio.current_branch(root)

    gitio.checkout_branch(root, "publish/demo", main)
    assert gitio.current_branch(root) == "publish/demo"
    (root / "a.txt").write_text("v2", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v2")

    gitio.checkout(root, main)
    assert gitio.current_branch(root) == main
    assert (root / "a.txt").read_text(encoding="utf-8") == "v1"

    # checkout -B lần 2 reset branch về start_point
    gitio.checkout_branch(root, "publish/demo", main)
    assert (root / "a.txt").read_text(encoding="utf-8") == "v1"
    gitio.checkout(root, main)


def test_push_branch_to_local_bare_origin(tmp_path, run_git):
    from center_kb import gitio

    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    (root / "a.txt").write_text("v1", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    gitio.push_branch(root, gitio.current_branch(root))
    gitio.checkout_branch(root, "publish/demo", "HEAD")
    gitio.push_branch(root, "publish/demo")
    out = run_git(origin, "branch")
    assert "publish/demo" in out
```

Tạo `tests/test_ghio.py`:

```python
import subprocess

import pytest

from center_kb import ghio


def _proc(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_pr_url_for_branch_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ghio, "_run_gh",
        lambda root, *a: _proc(0, "https://github.com/org/hub/pull/7\n"),
    )
    assert ghio.pr_url_for_branch(tmp_path, "publish/x") == "https://github.com/org/hub/pull/7"


def test_pr_url_for_branch_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(1, "", "no pr"))
    assert ghio.pr_url_for_branch(tmp_path, "publish/x") == ""


def test_create_pr_returns_url(tmp_path, monkeypatch):
    seen: dict = {}

    def fake(root, *args):
        seen["args"] = args
        return _proc(0, "https://github.com/org/hub/pull/9\n")

    monkeypatch.setattr(ghio, "_run_gh", fake)
    url = ghio.create_pr(tmp_path, "publish/x", title="t", body="b")
    assert url == "https://github.com/org/hub/pull/9"
    assert seen["args"][:2] == ("pr", "create")


def test_create_pr_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(1, "", "boom"))
    with pytest.raises(ghio.GHError):
        ghio.create_pr(tmp_path, "publish/x", title="t", body="b")
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_gitio.py tests/test_ghio.py -q`

- [ ] **Step 3: Implement** — cuối `src/center_kb/gitio.py`:

```python
def current_branch(root: Path) -> str:
    proc = _run(root, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"could not get current branch: {proc.stderr.strip()}")
    return proc.stdout.strip()


def checkout_branch(root: Path, name: str, start_point: str) -> None:
    """Tạo/reset branch `name` tại `start_point` rồi switch sang nó (checkout -B)."""
    proc = _run(root, "checkout", "-B", name, start_point)
    if proc.returncode != 0:
        raise GitError(f"checkout -B {name} failed: {proc.stderr.strip()}")


def checkout(root: Path, name: str) -> None:
    proc = _run(root, "checkout", name)
    if proc.returncode != 0:
        raise GitError(f"checkout {name} failed: {proc.stderr.strip()}")


def push_branch(root: Path, branch: str) -> None:
    """Force-push branch làm việc (publish/<rid> thuộc sở hữu của publisher)."""
    proc = _run(root, "push", "--force", "origin", branch)
    if proc.returncode != 0:
        raise GitError(f"push branch '{branch}' failed: {proc.stderr.strip()}")
```

Tạo `src/center_kb/ghio.py`:

```python
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GHError(RuntimeError):
    """GitHub CLI (`gh`) failed or is missing."""


def _run_gh(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=root, capture_output=True, text=True)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def pr_url_for_branch(root: Path, branch: str) -> str:
    """URL của PR đang mở cho `branch`; '' nếu chưa có."""
    proc = _run_gh(root, "pr", "view", branch, "--json", "url", "--jq", ".url")
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def create_pr(root: Path, branch: str, title: str, body: str) -> str:
    proc = _run_gh(
        root, "pr", "create", "--head", branch, "--title", title, "--body", body
    )
    if proc.returncode != 0:
        raise GHError(f"gh pr create failed: {proc.stderr.strip()}")
    lines = proc.stdout.strip().splitlines()
    return lines[-1] if lines else ""
```

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_gitio.py tests/test_ghio.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/gitio.py src/center_kb/ghio.py tests/test_gitio.py tests/test_ghio.py
git commit -m "feat: git branch helpers + gh CLI wrapper for PR-mode publish"
```

---

### Task 5: `publish.py` — mirror L0→L3, regen index tổng, direct + PR mode

**Files:**
- Rewrite: `src/center_kb/publish.py`
- Rewrite: `tests/test_publish.py`

**Interfaces:**
- Consumes: `federation.write_federation_index`, `gitio.*` (Task 4), `ghio.*` (Task 4), `hub_mod.resolve_hub`.
- Produces: `publish(kb_dir, hub_ref, repo_id=None, max_retries=3, mode="auto") -> PublishReport`; `PublishReport` {repo_id, source_commit, n_docs, pushed, **mode: str = "direct"**, **pr_url: str = ""**}; `PublishError`. mode: `"auto"` → `"pr"` khi hub có remote chứa "github" + `gh` sẵn, ngược lại `"direct"`. Task 9 (doctor test) và Task 15 (e2e) gọi `publish`.
- **Hành vi bỏ:** check va chạm repo-id với doc-id trong `.kb` của hub (hub .kb không còn được đọc).

- [ ] **Step 1: Rewrite `tests/test_publish.py`** (thay toàn bộ; giữ triết lý hermetic — origin là bare repo local):

```python
from pathlib import Path

import pytest

from center_kb import ghio, gitio, models
from center_kb.federation import FederationMeta, write_federation_index
from center_kb.publish import PublishError, publish
from tests.conftest import make_fed_entry


@pytest.fixture
def hub_with_origin(hub_worktree, run_git, tmp_path):
    origin = tmp_path / "hub-origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    return hub_worktree


def test_direct_publish_mirrors_full_tree(git_kb, hub_worktree):
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"
    assert report.n_docs == 1
    entry = hub_worktree / "federation" / "demo-kb"
    assert (entry / "index.yaml").exists()
    assert (entry / "demo-doc" / "_manifest.yaml").exists()
    assert (entry / "demo-doc" / "ch1-records.md").exists()       # L2
    assert (entry / "demo-doc" / "ch1-records.raw.md").exists()   # L3
    meta = models.load_yaml_model(entry / "_meta.yaml", FederationMeta)
    assert meta.repo_id == "demo-kb"
    assert meta.source_commit == report.source_commit


def test_direct_publish_regenerates_aggregate_index(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    idx = models.load_yaml_model(
        hub_worktree / "federation" / "index.yaml", models.FederationIndex
    )
    assert [(e.repo_id, e.doc_id) for e in idx.docs] == [("demo-kb", "demo-doc")]


def test_direct_publish_commits_on_hub(git_kb, hub_worktree, run_git):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    log = run_git(hub_worktree, "log", "--oneline")
    assert "publish: demo-kb" in log


def test_republish_replaces_entry_wholesale(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    stray = hub_worktree / "federation" / "demo-kb" / "stale-doc"
    stray.mkdir()
    (stray / "x.md").write_text("stale", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert not stray.exists()


def test_invalid_repo_id_rejected(git_kb, hub_worktree):
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="../evil")


def test_unreachable_hub_raises(git_kb, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "does-not-exist"))


def test_auto_mode_is_direct_for_local_path_hub(git_kb, hub_worktree, monkeypatch):
    # dev machine có thể có gh thật — chặn để auto-detect chỉ phụ thuộc remote
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"


def test_pr_mode_pushes_branch_and_opens_pr(git_kb, hub_with_origin, monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(ghio, "pr_url_for_branch", lambda root, branch: "")

    def fake_create(root, branch, title, body):
        calls["branch"] = branch
        calls["title"] = title
        return "https://github.com/org/hub/pull/7"

    monkeypatch.setattr(ghio, "create_pr", fake_create)
    report = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert report.mode == "pr"
    assert report.pr_url.endswith("/pull/7")
    assert calls["branch"] == "publish/demo-kb"
    # worktree hub trở về branch gốc, main không dính commit publish
    assert not (hub_with_origin / "federation" / "demo-kb").exists()
    assert gitio.current_branch(hub_with_origin) in ("main", "master")


def test_pr_mode_updates_existing_pr_without_creating(git_kb, hub_with_origin, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(
        ghio, "pr_url_for_branch",
        lambda root, branch: "https://github.com/org/hub/pull/7",
    )

    def boom(root, branch, title, body):
        raise AssertionError("create_pr must not be called when a PR is open")

    monkeypatch.setattr(ghio, "create_pr", boom)
    report = publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert report.pr_url.endswith("/pull/7")


def test_pr_mode_without_gh_raises_with_two_exits(git_kb, hub_with_origin, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: False)
    with pytest.raises(PublishError) as exc:
        publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="pr")
    assert "gh" in str(exc.value) and "--direct" in str(exc.value)


def test_direct_push_race_reindexes_after_rebase(git_kb, hub_with_origin, run_git, tmp_path):
    rival = tmp_path / "rival-clone"
    run_git(tmp_path, "clone", str(tmp_path / "hub-origin.git"), str(rival))
    run_git(rival, "config", "user.name", "t")
    run_git(rival, "config", "user.email", "t@t")
    make_fed_entry(rival / "federation", "other-kb", "other-doc")
    write_federation_index(rival / "federation")
    run_git(rival, "add", "-A")
    run_git(rival, "commit", "-m", "publish: other-kb")
    run_git(rival, "push")

    publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", mode="direct")

    idx = models.load_yaml_model(
        hub_with_origin / "federation" / "index.yaml", models.FederationIndex
    )
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("demo-kb", "demo-doc"),
        ("other-kb", "other-doc"),
    }
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_publish.py -q`

- [ ] **Step 3: Rewrite `src/center_kb/publish.py`** (thay toàn bộ):

```python
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from center_kb import federation, ghio, gitio, models
from center_kb import hub as hub_mod

_REPO_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

PR_BODY_TEMPLATE = (
    "Publish snapshot of repo '{rid}' @ {commit}.\n\n"
    "Merging this PR makes the content searchable across the federation."
)


class PublishError(RuntimeError):
    """Publishing the snapshot to the hub failed."""


@dataclass
class PublishReport:
    repo_id: str
    source_commit: str
    n_docs: int
    pushed: bool
    mode: str = "direct"  # "direct" | "pr"
    pr_url: str = ""


def _snapshot(
    kb_abs: Path, handle: hub_mod.HubHandle, rid: str, source_commit: str
) -> int:
    """Mirror toàn bộ .kb/ → federation/<rid>/ rồi đánh lại index tổng."""
    dest = handle.federation_dir / rid
    fed_root = handle.federation_dir.resolve()
    if not dest.resolve().is_relative_to(fed_root):
        raise PublishError(
            f"repo-id '{rid}' escapes the federation/ directory on the hub — refusing to publish"
        )
    local_index = models.load_yaml_model(kb_abs / "index.yaml", models.KBIndex)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(kb_abs, dest)
    meta = federation.FederationMeta(
        repo_id=rid,
        source_url=gitio.remote_url(gitio.git_root(kb_abs)),
        source_commit=source_commit,
        published_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    models.save_yaml_model(dest / "_meta.yaml", meta)
    federation.write_federation_index(handle.federation_dir)
    return len(local_index.docs)


def publish(
    kb_dir: Path,
    hub_ref: str,
    repo_id: str | None = None,
    max_retries: int = 3,
    mode: str = "auto",
) -> PublishReport:
    kb_abs = kb_dir.resolve()
    source_root = gitio.git_root(kb_abs)
    source_commit = gitio.head_commit(source_root)
    rid = repo_id or source_root.name
    if not _REPO_ID_RE.fullmatch(rid) or rid in {".", ".."}:
        raise PublishError(
            f"repo-id '{rid}' is invalid — only letters/digits/._- allowed, no path separators"
        )
    handle = hub_mod.resolve_hub(hub_ref)
    if handle is None:
        raise PublishError(f"could not reach hub '{hub_ref}'")

    if mode == "auto":
        use_pr = (
            gitio.has_remote(handle.root)
            and "github" in gitio.remote_url(handle.root)
            and ghio.gh_available()
        )
        mode = "pr" if use_pr else "direct"
    if mode == "pr":
        return _publish_pr(kb_abs, handle, rid, source_commit)
    return _publish_direct(kb_abs, handle, rid, source_commit, max_retries)


def _publish_direct(
    kb_abs: Path,
    handle: hub_mod.HubHandle,
    rid: str,
    source_commit: str,
    max_retries: int,
) -> PublishReport:
    n_docs = _snapshot(kb_abs, handle, rid, source_commit)
    committed = gitio.commit_paths(
        handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
    )
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
                        f"push to hub failed after {max_retries} attempts (race?)"
                    )
                gitio.pull_rebase(handle.root)
                # repo khác vừa publish — index tổng trong commit của ta có thể
                # thiếu docs của họ; regen (deterministic) rồi commit phần sửa
                federation.write_federation_index(handle.federation_dir)
                gitio.commit_paths(
                    handle.root,
                    f"publish: reindex after rebase ({rid})",
                    ["federation"],
                )
    return PublishReport(rid, source_commit, n_docs, pushed, mode="direct")


def _publish_pr(
    kb_abs: Path, handle: hub_mod.HubHandle, rid: str, source_commit: str
) -> PublishReport:
    if not ghio.gh_available():
        raise PublishError(
            "PR mode needs the GitHub CLI — install `gh` (https://cli.github.com) "
            "or run `kb publish --direct` if direct pushes are allowed"
        )
    branch = f"publish/{rid}"
    original = gitio.current_branch(handle.root)
    try:
        gitio.checkout_branch(handle.root, branch, original)
        n_docs = _snapshot(kb_abs, handle, rid, source_commit)
        committed = gitio.commit_paths(
            handle.root, f"publish: {rid} @ {source_commit}", ["federation"]
        )
        if not committed:
            return PublishReport(rid, source_commit, n_docs, False, mode="pr")
        gitio.push_branch(handle.root, branch)
        url = ghio.pr_url_for_branch(handle.root, branch)
        if not url:
            url = ghio.create_pr(
                handle.root,
                branch,
                title=f"publish: {rid} @ {source_commit}",
                body=PR_BODY_TEMPLATE.format(rid=rid, commit=source_commit),
            )
    finally:
        gitio.checkout(handle.root, original)
    return PublishReport(rid, source_commit, n_docs, True, mode="pr", pr_url=url)
```

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_publish.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py tests/test_publish.py
git commit -m "feat: publish full L0-L3 mirror with aggregate reindex, direct + PR modes"
```

---

### Task 6: `query.py` — search/get_section federation-only

**Files:**
- Rewrite: `src/center_kb/query.py`
- Rewrite: `tests/test_query.py`
- Delete: `tests/test_query_hub.py`
- Modify: `tests/test_query_semantic.py`

**Interfaces:**
- Consumes: `federation.load_federation` (Task 3), `embed.ensure_index/semantic_search` (không đổi), `HubHandle` (không đổi).
- Produces: `search(hub: HubHandle, text, tags=None, budget=2000, semantic=False, embedder=None) -> list[QueryResult]`; `get_section(hub, doc_id, section_id, level="l2", repo: str | None = None) -> QueryResult | None` (doc_id chấp nhận dạng `repo:doc`); `AmbiguousDocError(doc_id, repo_ids)` (LookupError, message liệt kê `rid:doc`); `QueryResult.source` = repo-id; citation = `rid:doc §sec (revision)`; `tokenize` giữ nguyên. **Xóa** `include_local`, `_Candidate.pointer`, mọi nhánh local/hub-.kb.
- Embeddings: mỗi repo con 1 db `<hub.root>/.kb-work/embeddings-<rid>.db`.

- [ ] **Step 1: Rewrite `tests/test_query.py`** (thay toàn bộ):

```python
import pytest

from center_kb.hub import HubHandle
from center_kb.query import AmbiguousDocError, get_section, search
from tests.conftest import make_fed_entry


def _handle(fed_hub) -> HubHandle:
    return HubHandle(root=fed_hub)


def test_search_returns_full_l2_with_repo_citation(fed_hub):
    results = search(_handle(fed_hub), "restrictive airspace designation")
    assert results
    top = results[0]
    assert top.source == "arinc-kb"
    assert top.citation.startswith("arinc-kb:arinc-424 §5.3")
    assert "Condensed: restrictive airspace" in top.content
    assert top.match_mode == "keyword"


def test_search_covers_all_federation_repos(fed_hub):
    results = search(_handle(fed_hub), "airspace designation type")
    assert {r.source for r in results} == {"arinc-kb", "icao-kb"}


def test_search_tag_filter(fed_hub):
    results = search(_handle(fed_hub), "airspace", tags=["arinc424"])
    assert results and all(r.source == "arinc-kb" for r in results)


def test_search_empty_federation_returns_empty(tmp_path):
    (tmp_path / "federation").mkdir()
    (tmp_path / ".kb").mkdir()
    assert search(HubHandle(root=tmp_path), "anything") == []


def test_search_no_token_overlap_returns_empty(fed_hub):
    assert search(_handle(fed_hub), "zzz qqq xxx") == []


def test_search_budget_caps_results(fed_hub):
    results = search(_handle(fed_hub), "airspace designation type", budget=1)
    assert len(results) == 1  # luôn trả >= 1 khi có match


def test_get_section_unqualified_unique(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-424", "5.3")
    assert r is not None
    assert r.source == "arinc-kb"
    assert r.citation.startswith("arinc-kb:arinc-424 §5.3")


def test_get_section_l3_and_colon_form(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-kb:arinc-424", "§5.3", level="l3")
    assert r is not None
    assert "Full raw restrictive airspace" in r.content


def test_get_section_repo_param(fed_hub):
    r = get_section(_handle(fed_hub), "arinc-424", "5.3", repo="arinc-kb")
    assert r is not None and r.source == "arinc-kb"


def test_get_section_ambiguous_raises_with_candidates(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    with pytest.raises(AmbiguousDocError) as exc:
        get_section(_handle(fed_hub), "arinc-424", "5.3")
    assert "arinc-kb:arinc-424" in str(exc.value)
    assert "dup-kb:arinc-424" in str(exc.value)


def test_get_section_missing_returns_none(fed_hub):
    assert get_section(_handle(fed_hub), "ghost", "1.1") is None
    assert get_section(_handle(fed_hub), "arinc-424", "9.9") is None
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_query.py -q` (signature cũ nhận `kb_dir`).

- [ ] **Step 3: Rewrite `src/center_kb/query.py`** (thay toàn bộ):

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rank_bm25 import BM25Plus

from center_kb import models
from center_kb.embed import SEMANTIC_FALLBACK_THRESHOLD
from center_kb.mdutils import count_tokens, slice_section

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

logger = logging.getLogger("center_kb.query")


class AmbiguousDocError(LookupError):
    """doc_id tồn tại ở nhiều repo trong federation — cần qualify repo:doc."""

    def __init__(self, doc_id: str, repo_ids: list[str]) -> None:
        self.doc_id = doc_id
        self.repo_ids = repo_ids
        options = ", ".join(f"{rid}:{doc_id}" for rid in repo_ids)
        super().__init__(
            f"doc '{doc_id}' exists in {len(repo_ids)} federation repos — "
            f"qualify the ref: {options}"
        )


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = ""  # repo-id trong federation
    match_mode: str = "keyword"  # "keyword" | "semantic"


@dataclass
class _Candidate:
    doc: models.IndexEntry
    sec: models.SectionEntry
    kb_dir: Path  # federation/<repo-id>/ (mirror .kb)
    source: str  # repo-id
    citation: str


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(
    repo_id: str, doc: models.IndexEntry | models.Manifest, section_id: str
) -> str:
    base = f"{repo_id}:{doc.id} §{section_id}"
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


def _repo_candidates(
    repo_kb: Path, repo_id: str, tags: list[str] | None
) -> list[_Candidate]:
    index_path = repo_kb / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)
    out: list[_Candidate] = []
    for doc in _filter_tags(index.docs, tags):
        manifest_path = repo_kb / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            out.append(
                _Candidate(
                    doc=doc, sec=sec, kb_dir=repo_kb, source=repo_id,
                    citation=_citation(repo_id, doc, sec.id),
                )
            )
    return out


def _gather_candidates(hub: "HubHandle", tags: list[str] | None) -> list[_Candidate]:
    from center_kb.federation import load_federation

    out: list[_Candidate] = []
    for repo in load_federation(hub.federation_dir):
        out += _repo_candidates(repo.kb_dir, repo.meta.repo_id, tags)
    return out


def _candidate_content(c: _Candidate) -> str | None:
    l2_path = c.kb_dir / c.doc.id / f"{c.sec.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), c.sec.id)


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    embedder=None,  # center_kb.embed.Embedder | None — injectable cho test
) -> list[QueryResult]:
    corpus = _gather_candidates(hub, tags)
    if not corpus:
        return []

    section_tokens = [tokenize(f"{c.sec.title} {c.sec.summary}") for c in corpus]
    bm25 = BM25Plus(section_tokens)
    query_token_list = tokenize(text)
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
            # BM25Plus cộng baseline idf*delta cho mọi term trong vocab —
            # section không chung token nào với query vẫn có thể score > 0.
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

    top_score = results[0].score if results else 0.0
    if semantic or not results or top_score < SEMANTIC_FALLBACK_THRESHOLD:
        semantic_results = _semantic_fallback(hub, corpus, text, budget, embedder)
        if semantic_results:
            return semantic_results
    return results


def _semantic_fallback(
    hub: "HubHandle",
    corpus: list[_Candidate],
    text: str,
    budget: int,
    embedder,
) -> list[QueryResult]:
    """Routing bước 3: KNN sqlite-vec trên từng repo trong federation."""
    from center_kb import embed as embed_mod
    from center_kb.federation import load_federation

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if embedder is None:
        return []
    by_key = {(c.source, c.doc.id, c.sec.id): c for c in corpus}
    hits: list[tuple[str, str, str, float]] = []  # rid, doc, sec, score
    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        db_path = hub.root / ".kb-work" / f"embeddings-{rid}.db"
        try:
            embed_mod.ensure_index(repo.kb_dir, db_path, embedder)
            for doc_id, sec_id, score in embed_mod.semantic_search(
                db_path, embedder, text
            ):
                hits.append((rid, doc_id, sec_id, score))
        except Exception as exc:  # embedding best-effort — không được phá query
            logger.warning("semantic search error (%s) — skipping: %s", rid, exc)
    results: list[QueryResult] = []
    used = 0
    for rid, doc_id, sec_id, score in sorted(hits, key=lambda h: -h[3]):
        c = by_key.get((rid, doc_id, sec_id))
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
                tokens=n_tokens, source=rid, match_mode="semantic",
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _get_section_in(
    repo_kb: Path, repo_id: str, doc_id: str, section_id: str, level: str
) -> QueryResult | None:
    manifest_path = repo_kb / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
    suffix = ".raw.md" if level == "l3" else ".md"
    path = repo_kb / doc_id / f"{sec.file}{suffix}"
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
        citation=_citation(repo_id, manifest, section_id),
        content=content,
        tokens=count_tokens(content),
        source=repo_id,
    )


def get_section(
    hub: "HubHandle",
    doc_id: str,
    section_id: str,
    level: str = "l2",
    repo: str | None = None,
) -> QueryResult | None:
    from center_kb.federation import load_federation

    section_id = section_id.lstrip("§")
    if ":" in doc_id and repo is None:
        repo, doc_id = doc_id.split(":", 1)
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    return _get_section_in(r.kb_dir, r.meta.repo_id, doc_id, section_id, level)
```

- [ ] **Step 4: Xóa test cũ + adapt semantic test**

```bash
git rm tests/test_query_hub.py
```

Trong `tests/test_query_semantic.py`: đổi mọi lời gọi `search(fixture_kb, ..., hub=..., ...)` / `search(kb, ...)` thành `search(HubHandle(root=fed_hub), ..., embedder=fake)` với fixture `fed_hub`; import `from center_kb.hub import HubHandle`; db path assertion (nếu có) đổi thành `fed_hub / ".kb-work" / "embeddings-arinc-kb.db"`. FakeEmbedder giữ nguyên. Mẫu một test sau chuyển đổi:

```python
def test_semantic_fallback_kicks_in_when_bm25_misses(fed_hub, fake_embedder):
    from center_kb.hub import HubHandle
    from center_kb.query import search

    results = search(
        HubHandle(root=fed_hub),
        "văn bản không chung token nào",
        embedder=fake_embedder,
        semantic=True,
    )
    assert results and results[0].match_mode == "semantic"
    assert (fed_hub / ".kb-work" / "embeddings-arinc-kb.db").exists()
```

(giữ nguyên tên fixture embedder hiện có của file — nếu file đang định nghĩa `FakeEmbedder` class thì tái dùng; chỉ đổi nguồn dữ liệu + signature.)

- [ ] **Step 5: PASS** — `.venv/bin/python -m pytest tests/test_query.py tests/test_query_semantic.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/query.py tests/test_query.py tests/test_query_semantic.py
git rm -q tests/test_query_hub.py 2>/dev/null || true
git commit -m "feat!: search/get_section read only the hub federation (full L2/L3)"
```

---

### Task 7: `kbcontext.py` — pin HEAD hub, auto-qualify refs

**Files:**
- Modify: `src/center_kb/kbcontext.py` (chỉ hàm `build_context_block`; parse/render/KBRef giữ nguyên)
- Modify: `tests/test_kbcontext.py`

**Interfaces:**
- Consumes: `federation.load_federation`, `gitio.head_commit/git_root`, `query.AmbiguousDocError`, `HubHandle`.
- Produces: `build_context_block(hub: HubHandle, refs: list[str], tags=None) -> tuple[str, str | None]` — phần tử 2 là **stale warning** (thay dirty_warning cũ). Refs được auto-qualify (`ref.repo_id` gán tại chỗ). `parse()`/`render()`/`KBContext.hub_version` không đổi (tương thích đọc block cũ).

- [ ] **Step 1: Viết test fail** — trong `tests/test_kbcontext.py`: GIỮ nguyên các test parse/render/parse_ref; THAY các test về `build_context_block` bằng:

```python
import pytest

from center_kb.hub import HubHandle
from center_kb.kbcontext import (
    KBContextError,
    KBRefNotFoundError,
    build_context_block,
    parse,
)
from tests.conftest import make_fed_entry


def test_build_block_pins_hub_head_and_qualifies(fed_hub, run_git):
    block, warning = build_context_block(HubHandle(root=fed_hub), ["arinc-424 §5.3"])
    head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    assert f'version: "{head}"' in block
    assert "- arinc-kb:arinc-424 §5.3" in block
    assert "hub_version" not in block
    assert warning is None
    assert parse(block).refs[0].repo_id == "arinc-kb"


def test_build_block_multiple_refs_and_tags(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-annex-2 §1.1"],
        tags=["airspace"],
    )
    assert "- arinc-kb:arinc-424 §5.3" in block
    assert "- icao-kb:icao-annex-2 §1.1" in block
    assert "tags: [airspace]" in block


def test_build_block_unknown_ref_raises(fed_hub):
    with pytest.raises(KBRefNotFoundError):
        build_context_block(HubHandle(root=fed_hub), ["ghost-doc §9.9"])


def test_build_block_unknown_section_raises(fed_hub):
    with pytest.raises(KBRefNotFoundError):
        build_context_block(HubHandle(root=fed_hub), ["arinc-424 §9.9"])


def test_build_block_ambiguous_doc_raises(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    with pytest.raises(KBContextError) as exc:
        build_context_block(HubHandle(root=fed_hub), ["arinc-424 §5.3"])
    assert "dup-kb:arinc-424" in str(exc.value)


def test_build_block_stale_hub_warns(fed_hub):
    handle = HubHandle(root=fed_hub, stale=True, age_seconds=120.0)
    _, warning = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    assert warning is not None and "stale" in warning
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_kbcontext.py -q`

- [ ] **Step 3: Implement** — thay toàn bộ hàm `build_context_block` trong `src/center_kb/kbcontext.py` (đổi cả docstring; xóa import `Path` nếu không còn dùng):

```python
def build_context_block(
    hub: "HubHandle",
    refs: list[str],
    tags: list[str] | None = None,
) -> tuple[str, str | None]:
    """Validate refs trên hub federation, auto-qualify repo id, pin HEAD hub.

    Returns (block_text, stale_warning): stale_warning là một dòng cảnh báo
    khi hub cache đang stale (offline), ngược lại None.
    """
    from center_kb import gitio, models
    from center_kb.federation import load_federation
    from center_kb.query import AmbiguousDocError

    ref_list = [parse_ref(r) for r in refs if r.strip()]
    if not ref_list:
        raise KBContextError(
            "--refs is empty — need at least 1 ref, e.g. 'arinc-kb:arinc-424 §5.3'"
        )

    repos = load_federation(hub.federation_dir)
    by_rid = {r.meta.repo_id: r for r in repos}
    bad: list[str] = []
    for ref in ref_list:
        if ref.repo_id is None:
            holders = [
                r.meta.repo_id
                for r in repos
                if (r.kb_dir / ref.doc_id / "_manifest.yaml").exists()
            ]
            if len(holders) > 1:
                raise KBContextError(str(AmbiguousDocError(ref.doc_id, holders)))
            if not holders:
                bad.append(str(ref))
                continue
            ref.repo_id = holders[0]
        repo = by_rid.get(ref.repo_id)
        found = False
        if repo is not None:
            manifest_path = repo.kb_dir / ref.doc_id / "_manifest.yaml"
            if manifest_path.exists():
                manifest = models.load_yaml_model(manifest_path, models.Manifest)
                found = any(s.id == ref.section_id for s in manifest.sections)
        if not found:
            bad.append(str(ref))
    if bad:
        raise KBRefNotFoundError(
            f"Ref could not be resolved in the hub federation: {', '.join(bad)}"
        )

    version = gitio.head_commit(gitio.git_root(hub.root))
    warning = None
    if hub.stale:
        age = f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"
        warning = (
            f"[warn] hub cache is stale ({age}) — the pinned hash may lag the hub"
        )
    ctx = KBContext(
        version=version,
        refs=ref_list,
        tags=[t.strip() for t in (tags or []) if t.strip()],
    )
    return render(ctx), warning
```

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_kbcontext.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/kbcontext.py tests/test_kbcontext.py
git commit -m "feat!: kb-context pins a single hub HEAD commit, refs auto-qualified repo:doc"
```

---

### Task 8: `resolve.py` — resolve qua git history của hub

**Files:**
- Modify: `src/center_kb/resolve.py` (giữ `ResolvedRef`, `_broken`, `_worktree_section`, `_resolve_one`, `render_resolved`; thay `resolve_refs`; XÓA `_resolve_hub_ref`, `_resolve_remote_ref`, `_doc_ids`)
- Rewrite: `tests/test_resolve.py`
- Delete: `tests/test_resolve_hub.py`

**Interfaces:**
- Consumes: `build_context_block` (Task 7), `federation.load_federation`, `gitio.rev_exists/git_root/read_at`.
- Produces: `resolve_refs(hub: HubHandle, ctx: KBContext) -> list[ResolvedRef]`. Block cũ (version không tồn tại trong history hub) → mọi ref `broken` với reason chứa "re-pin". `_resolve_one` tái dùng nguyên vẹn với `kb_dir = hub.federation_dir / rid`, `root = git_root(hub.root)`, `rev = ctx.version`.

- [ ] **Step 1: Rewrite `tests/test_resolve.py`** (thay toàn bộ):

```python
from center_kb import kbcontext
from center_kb.hub import HubHandle
from center_kb.kbcontext import KBContext, KBRef, build_context_block
from center_kb.resolve import render_resolved, resolve_refs
from tests.conftest import make_fed_entry


def _ctx_for(fed_hub, refs):
    block, _ = build_context_block(HubHandle(root=fed_hub), refs)
    return kbcontext.parse(block)


def test_resolve_ok_roundtrip(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    results = resolve_refs(handle, ctx)
    assert [r.status for r in results] == ["ok"]
    assert "Condensed: restrictive airspace" in results[0].content
    assert results[0].citation.startswith("arinc-kb:arinc-424 §5.3")


def test_resolve_stale_after_republish(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amendment republished")
    results = resolve_refs(handle, ctx)
    assert results[0].status == "stale"
    # nội dung trả về vẫn là bản pinned
    assert "designation codes" in results[0].content


def test_resolve_unqualified_ref_disambiguated(fed_hub):
    handle = HubHandle(root=fed_hub)
    head_block, _ = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    version = kbcontext.parse(head_block).version
    ctx = KBContext(
        version=version, refs=[KBRef(doc_id="arinc-424", section_id="5.3")]
    )
    results = resolve_refs(handle, ctx)
    assert results[0].status == "ok"


def test_resolve_unqualified_ambiguous_is_broken(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    head_block, _ = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    version = kbcontext.parse(head_block).version
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    ctx = KBContext(
        version=version, refs=[KBRef(doc_id="arinc-424", section_id="5.3")]
    )
    results = resolve_refs(handle, ctx)
    assert results[0].status == "broken"
    assert "re-pin" in results[0].reason


def test_resolve_legacy_block_broken_with_hint(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = KBContext(
        version="deadbee",  # commit của repo local cũ — không có trong hub
        refs=[KBRef(doc_id="arinc-424", section_id="5.3")],
    )
    results = resolve_refs(handle, ctx)
    assert all(r.status == "broken" for r in results)
    assert "re-pin" in results[0].reason


def test_render_resolved_shows_status(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    text = render_resolved(resolve_refs(handle, ctx))
    assert "status=ok" in text
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_resolve.py -q`

- [ ] **Step 3: Implement** — trong `src/center_kb/resolve.py`: xóa `_resolve_hub_ref`, `_resolve_remote_ref`, `_doc_ids`; thay `resolve_refs` bằng:

```python
def resolve_refs(hub: "HubHandle", ctx: KBContext) -> list[ResolvedRef]:
    from center_kb.federation import load_federation

    root = gitio.git_root(hub.root)
    if not gitio.rev_exists(root, ctx.version):
        reason = (
            f"pinned commit {ctx.version} does not exist on the hub — the block "
            "was pinned under the old local-first architecture (or hub history "
            "was rewritten); re-pin with kb_context_new"
        )
        return [_broken(ref, reason, pinned_rev=ctx.version) for ref in ctx.refs]

    repos = load_federation(hub.federation_dir)
    out: list[ResolvedRef] = []
    for ref in ctx.refs:
        if ref.repo_id is None:
            holders = [
                r.meta.repo_id
                for r in repos
                if (r.kb_dir / ref.doc_id / "_manifest.yaml").exists()
            ]
            if len(holders) != 1:
                out.append(
                    _broken(
                        ref,
                        "ref has no repo id and cannot be disambiguated in the "
                        "current federation — re-pin with kb_context_new",
                    )
                )
                continue
            ref.repo_id = holders[0]
        out.append(
            _resolve_one(hub.federation_dir / ref.repo_id, root, ctx.version, ref)
        )
    return out
```

Cập nhật `TYPE_CHECKING` import nếu cần (`HubHandle` đã có). `_resolve_one`/`_worktree_section` giữ nguyên — chúng nhận `kb_dir` bất kỳ, hoạt động trên mirror federation.

- [ ] **Step 4: PASS + xóa file cũ**

```bash
.venv/bin/python -m pytest tests/test_resolve.py -q
git rm tests/test_resolve_hub.py
```

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/resolve.py tests/test_resolve.py
git commit -m "feat!: kb-context resolution runs against hub git history only"
```

---

### Task 9: `doctor.py` — checks mới cho kiến trúc hub-first

**Files:**
- Modify: `src/center_kb/doctor.py` (thay `check_hub` + xóa `_COLLISION_GUIDE`; thêm `_kb_tree_digest`; `check_kb`/`check_context` giữ nguyên — riêng `check_context` đổi signature sang hub, xem Step 3)
- Rewrite: `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: `publish` (Task 5), `federation.build_federation_index/load_federation`, `models.FederationIndex`.
- Produces: `check_hub(kb_dir, handle, repo_id=None) -> tuple[list[Issue], bool]` — handle None → **error** (trước là warning); stale → warning + True; entry format cũ → warning; `federation/index.yaml` thiếu/lệch → error nhắc `kb reindex`; local `.kb` khác snapshot đã publish → warning nhắc `kb publish`; doc-id trùng giữa các repo → warning. `check_context(hub_kb_dir_bỏ)` → `check_context(text, hub) -> tuple[list[Issue], list[ResolvedRef]]` (bỏ tham số kb_dir vì resolve giờ chỉ cần hub).

- [ ] **Step 1: Rewrite `tests/test_doctor_hub.py`** (thay toàn bộ):

```python
from center_kb.doctor import check_hub
from center_kb.hub import HubHandle
from center_kb.publish import publish
from tests.conftest import make_fed_entry


def test_hub_unreachable_is_error(fixture_kb):
    issues, stale = check_hub(fixture_kb, None)
    assert stale is False
    assert issues and issues[0].level == "error"


def test_stale_cache_warns_and_flags(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    handle = HubHandle(root=hub_worktree, stale=True, age_seconds=90.0)
    issues, stale = check_hub(git_kb["kb"], handle, repo_id="demo-kb")
    assert stale is True
    assert any("stale" in i.message for i in issues)


def test_clean_state_after_publish_is_ok(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    issues, stale = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert issues == [] and stale is False


def test_unpublished_repo_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="ghost-kb")
    assert any(i.level == "warning" and "kb publish" in i.message for i in issues)


def test_local_changes_since_publish_warn(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert any(
        i.level == "warning" and "differs from the published snapshot" in i.message
        for i in issues
    )


def test_out_of_sync_aggregate_index_errors(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8"
    )
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree), repo_id="demo-kb")
    assert any(i.level == "error" and "kb reindex" in i.message for i in issues)


def test_missing_aggregate_index_errors(git_kb, hub_worktree):
    # hub_worktree chưa từng publish → chưa có federation/index.yaml
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any(i.level == "error" and "kb reindex" in i.message for i in issues)


def test_old_format_entry_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    legacy = hub_worktree / "federation" / "legacy-kb" / "manifests"
    legacy.mkdir(parents=True)
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("legacy-kb" in i.message and "kb publish" in i.message for i in issues)


def test_duplicate_doc_id_across_repos_warns(git_kb, hub_worktree):
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    make_fed_entry(hub_worktree / "federation", "dup-kb", "demo-doc")
    from center_kb.federation import write_federation_index

    write_federation_index(hub_worktree / "federation")
    issues, _ = check_hub(git_kb["kb"], HubHandle(root=hub_worktree))
    assert any("appears in 2 federation repos" in i.message for i in issues)
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_doctor_hub.py -q`

- [ ] **Step 3: Implement** — trong `src/center_kb/doctor.py`:

1. Xóa `_COLLISION_GUIDE`.
2. `check_context` đổi thành (resolve giờ chỉ cần hub):

```python
def check_context(
    text: str, hub: "HubHandle"
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(hub, ctx)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            issues.append(Issue("warning", f"{r.ref}: {r.reason}"))
    return issues, results
```

3. Thêm helper + thay `check_hub`:

```python
def _kb_tree_digest(root: Path) -> str:
    """Digest deterministic của một cây .kb (bỏ _meta.yaml — chỉ có ở snapshot)."""
    import hashlib

    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "_meta.yaml":
            continue
        h.update(path.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def check_hub(
    kb_dir: Path, handle: "HubHandle | None", repo_id: str | None = None
) -> tuple[list[Issue], bool]:
    """Sức khỏe hub-first. Returns (issues, hub_stale)."""
    from center_kb.federation import build_federation_index, load_federation

    if handle is None:
        return (
            [
                Issue(
                    "error",
                    "could not reach hub — the federation is the only read "
                    "source; check the network or the hub path",
                )
            ],
            False,
        )
    issues: list[Issue] = []
    hub_stale = False
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown"
        issues.append(
            Issue("warning", f"hub cache is stale (pull failed, age {age})")
        )
        hub_stale = True

    fed = handle.federation_dir
    if fed.is_dir():
        for child in sorted(p for p in fed.iterdir() if p.is_dir()):
            if (child / "manifests").is_dir():
                issues.append(
                    Issue(
                        "warning",
                        f"federation/{child.name} uses the old slim layout — "
                        "run `kb publish` from that repo to upgrade it",
                    )
                )

    index_path = fed / "index.yaml"
    if not index_path.exists():
        issues.append(
            Issue("error", "federation/index.yaml is missing — run `kb reindex`")
        )
    else:
        stored = models.load_yaml_model(index_path, models.FederationIndex)
        if stored != build_federation_index(fed):
            issues.append(
                Issue(
                    "error",
                    "federation/index.yaml is out of sync with the snapshots — "
                    "run `kb reindex`",
                )
            )

    if repo_id:
        entry = fed / repo_id
        if not entry.is_dir():
            issues.append(
                Issue(
                    "warning",
                    f"repo '{repo_id}' has not published to the hub yet — run `kb publish`",
                )
            )
        elif _kb_tree_digest(kb_dir.resolve()) != _kb_tree_digest(entry):
            issues.append(
                Issue(
                    "warning",
                    f"local .kb differs from the published snapshot "
                    f"federation/{repo_id} — run `kb publish`",
                )
            )

    counts = Counter(
        d.id for r in load_federation(fed) for d in r.index.docs
    )
    for doc_id, n in sorted(counts.items()):
        if n > 1:
            issues.append(
                Issue(
                    "warning",
                    f"doc-id '{doc_id}' appears in {n} federation repos — "
                    "refs must be repo-qualified (repo:doc)",
                )
            )
    return issues, hub_stale
```

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_doctor_hub.py -q` (test_doctor.py phần check_kb không đổi, chạy kèm: `tests/test_doctor.py` — nếu file đó có test `check_context(kb_dir, ...)` signature cũ thì đổi lời gọi sang `check_context(text, hub)` với fixture `fed_hub`.)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/doctor.py tests/test_doctor_hub.py tests/test_doctor.py
git commit -m "feat!: doctor checks hub reachability, unpublished drift, aggregate index sync"
```

---

### Task 10: `mcp.py` — server đọc federation, hub từ config

**Files:**
- Modify: `src/center_kb/mcp.py`
- Rewrite: `tests/test_mcp.py`
- Modify: `tests/test_mcp_http.py` (chỉ chỗ tạo `ServerConfig`)

**Interfaces:**
- Consumes: `config.require_hub/HubConfigError` (Task 1), `query.search/get_section/AmbiguousDocError` (Task 6), `kbcontext.build_context_block` (Task 7), `resolve.resolve_refs` (Task 8), `federation.load_federation`.
- Produces: `ServerConfig(kb_dir: Path, hub: str, transport="stdio", host, port)` — **hub là str bắt buộc**; `parse_args` fold env `CENTER_KB_HUB` + config file, thiếu → `SystemExit(HUB_GUIDE)`; tool `kb_get_section` thêm param `repo: str = ""`; 4 tool giữ tên. Task 13 (web) dùng `ServerConfig` mới.

- [ ] **Step 1: Rewrite `tests/test_mcp.py`** (thay toàn bộ):

```python
import pytest
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)

from center_kb.mcp import ServerConfig, create_server, parse_args
from tests.conftest import make_fed_entry


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _text(result) -> str:
    return result.content[0].text


def _config(fed_hub) -> ServerConfig:
    return ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub))


def test_parse_args_requires_hub(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    with pytest.raises(SystemExit):
        parse_args(["--kb", str(kb)])


def test_parse_args_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("hub: /srv/kb-hub\n", encoding="utf-8")
    config = parse_args(["--kb", str(kb)])
    assert config.hub == "/srv/kb-hub"


def test_parse_args_flag_beats_env_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB", "/from-env")
    kb = tmp_path / ".kb"
    kb.mkdir()
    config = parse_args(["--kb", str(kb), "--hub", "/from-flag"])
    assert config.hub == "/from-flag"


@pytest.mark.anyio
async def test_lists_exactly_four_tools(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_context_new", "kb_get_section", "kb_resolve", "kb_search",
        ]


@pytest.mark.anyio
async def test_kb_search_returns_federation_citation(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "arinc-kb:arinc-424 §5.3" in _text(result)
        assert "Condensed: restrictive airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_l3_and_repo_param(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-424", "section": "5.3", "level": "l3", "repo": "arinc-kb"},
        )
        assert "Full raw restrictive airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_ambiguous_lists_candidates(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "arinc-424", "section": "5.3"}
        )
        assert "dup-kb:arinc-424" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_not_found_lists_known_docs(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "ghost", "section": "1.1"}
        )
        assert "arinc-kb:arinc-424" in _text(result)


@pytest.mark.anyio
async def test_context_new_and_resolve_roundtrip(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        block = await client.call_tool(
            "kb_context_new", {"refs": ["arinc-424 §5.3"]}
        )
        assert "- arinc-kb:arinc-424 §5.3" in _text(block)
        resolved = await client.call_tool(
            "kb_resolve", {"kb_context": _text(block)}
        )
        assert "status=ok" in _text(resolved)


@pytest.mark.anyio
async def test_hub_unreachable_returns_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing"))
    server = create_server(config)
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "anything"})
        assert "hub unreachable" in _text(result)
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_mcp.py -q`

- [ ] **Step 3: Implement** — trong `src/center_kb/mcp.py`:

1. `ServerConfig.hub: str` (bỏ `= None`); import `os` lên đầu file.
2. `_known_docs` thay bằng bản federation:

```python
def _known_docs(hub) -> str:
    from center_kb.federation import load_federation

    return ", ".join(
        f"{r.meta.repo_id}:{d.id}"
        for r in load_federation(hub.federation_dir)
        for d in r.index.docs
    )
```

3. Trong `create_server`:

```python
HUB_DOWN = (
    "hub unreachable and no local cache — queries need the hub federation; "
    "check the network or the hub path, then try again"
)


def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("center-kb")

    def _hub():
        from center_kb.hub import resolve_hub

        return resolve_hub(config.hub)

    def _stale_note(hub) -> str:
        if hub is not None and hub.stale:
            age = f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"
            return f"[warn] hub cache is stale ({age}) — results may lag the hub\n\n"
        return ""
```

4. Bốn tool — thân mới (docstring giữ nội dung cũ, thêm 1 câu "Results come from the hub federation — unpublished local content never appears."):

```python
    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """<docstring cũ của kb_search + câu federation ở trên>"""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        results = search(hub, query, tags=tags, budget=budget)
        if not results:
            return "No matching section found — try dropping tags or changing keywords."
        note = _stale_note(hub)
        if len(results) >= 2 and results[0].score > 0:
            gap = (results[0].score - results[1].score) / results[0].score
            if gap < AMBIGUOUS_SCORE_GAP:
                note += (
                    f"Note: [{results[0].citation}] and [{results[1].citation}] "
                    "score closely — both may be relevant to your question; "
                    "review each before citing.\n\n"
                )
        return note + "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )

    @mcp.tool()
    def kb_get_section(
        doc: str, section: str, level: str = "l2", repo: str = ""
    ) -> str:
        """Fetch exactly one section: level 'l2' (condensed) or 'l3' (verbatim).
        `doc` accepts 'repo:doc' form; pass `repo` when the doc id alone is
        ambiguous across federation repos."""
        if level not in ("l2", "l3"):
            return f"level '{level}' is invalid — use 'l2' or 'l3'."
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        from center_kb.query import AmbiguousDocError

        try:
            result = get_section(hub, doc, section, level=level, repo=repo or None)
        except AmbiguousDocError as exc:
            return str(exc)
        if result is None:
            known = _known_docs(hub)
            hint = f" Available docs: {known}." if known else ""
            return f"Not found: {doc} §{section}.{hint}"
        return (
            _stale_note(hub)
            + f"--- [{result.citation}] ~{result.tokens}tk\n{result.content}"
        )

    @mcp.tool()
    def kb_context_new(refs: list[str], tags: list[str] | None = None) -> str:
        """<docstring cũ giữ nguyên>"""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        try:
            block, warning = kbcontext.build_context_block(hub, refs, tags=tags)
        except kbcontext.KBRefNotFoundError as exc:
            known = _known_docs(hub)
            hint = f" Available docs: {known}." if known else ""
            return f"{exc}{hint}"
        except kbcontext.KBContextError as exc:
            return str(exc)
        except gitio.GitError as exc:
            return str(exc)
        if warning:
            return f"{warning}\n\n{block}"
        return block

    @mcp.tool()
    def kb_resolve(kb_context: str) -> str:
        """<docstring cũ giữ nguyên>"""
        hub = _hub()
        if hub is None:
            return HUB_DOWN
        try:
            ctx = kbcontext.parse(kb_context)
        except kbcontext.KBContextError as exc:
            return f"kb-context error: {exc}"
        try:
            results = resolve_refs(hub, ctx)
        except gitio.GitError as exc:
            return f"git error: {exc}"
        return _stale_note(hub) + render_resolved(results)
```

5. `parse_args`:

```python
def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m center_kb.mcp", description="CENTER-KB MCP server"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"),
                    help="KB directory (chỉ để tìm .kb/config.yaml)")
    ap.add_argument("--hub", default=None,
                    help="kb-hub URL/path (default: env CENTER_KB_HUB, rồi .kb/config.yaml)")
    ap.add_argument("--transport", choices=("stdio", "http"), default="stdio",
                    help="stdio (default) or http (requires CENTER_KB_HTTP_TOKEN)")
    ap.add_argument("--host", default="127.0.0.1", help="Host to bind when --transport http")
    ap.add_argument("--port", type=int, default=8321, help="Port when --transport http")
    args = ap.parse_args(argv)
    from center_kb.config import HubConfigError, require_hub

    try:
        hub = require_hub(
            args.hub or os.environ.get("CENTER_KB_HUB", ""), args.kb
        )
    except HubConfigError as exc:
        raise SystemExit(str(exc))
    return ServerConfig(
        kb_dir=args.kb, hub=hub, transport=args.transport,
        host=args.host, port=args.port,
    )
```

Import bổ sung đầu file: `from center_kb.resolve import render_resolved, resolve_refs` (đổi từ `render_resolved, resolve_refs` cũ — giữ), bỏ import `models` nếu không còn dùng.

6. `tests/test_mcp_http.py`: mọi chỗ `ServerConfig(kb_dir=...)` thêm `hub=str(<fixture hub path>)` — dùng `fed_hub` nếu test cần search ra kết quả, hoặc `hub=str(tmp_path)` cho test thuần auth/transport.

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_mcp.py tests/test_mcp_http.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/mcp.py tests/test_mcp.py tests/test_mcp_http.py
git commit -m "feat!: MCP server reads only the hub federation; hub resolved from config"
```

---

### Task 11: `cli.py` — chuyển toàn bộ lệnh đọc sang hub, thêm `reindex`, bỏ `approve`

**Files:**
- Modify: `src/center_kb/cli.py`, `src/center_kb/build.py` KHÔNG đổi (khối embed nằm trong cli `build` command — xem Step 3.7)
- Modify: `tests/test_cli.py`, `tests/test_cli_hub.py`, `tests/test_cli_context.py`, `tests/test_cli_doctor_diff.py`, `tests/test_build.py` (nếu có test cho embed-refresh trong lệnh build thì xóa test đó)

**Interfaces:**
- Consumes: mọi API mới Task 1–9.
- Produces (CLI surface — Task 14/15 và template dựa vào):
  - `kb query TEXT [--tags] [--budget] [--kb-dir] [--hub] [--semantic]` — federation-only.
  - `kb get DOC SECTION [--level] [--repo] [--kb-dir] [--hub]`.
  - `kb publish [--hub] [--repo-id] [--kb-dir] [--pr/--direct]` (mặc định auto).
  - `kb reindex [--hub] [--kb-dir]` (mới).
  - `kb context new --refs ... [--tags] [--kb-dir] [--hub]`; `kb resolve SOURCE [--kb-dir] [--hub]`; `kb doctor [--kb-dir] [--context] [--hub]`.
  - `kb approve` **bị xóa**.
  - Helper nội bộ `_hub_or_exit(hub_flag: str, kb_dir: Path) -> HubHandle`.

- [ ] **Step 1: Viết test fail** — cập nhật test CLI. Quy tắc chuyển đổi chung cho MỌI file test CLI: (a) lệnh đọc nào trước đây chạy trên `fixture_kb` không hub → giờ thêm `--hub str(fed_hub)` và assert theo citation `rid:doc`; (b) test nào kiểm tra hành vi "local wins"/"[remote]" → xóa. Các test mới bắt buộc (thêm vào `tests/test_cli_hub.py`, thay nội dung cũ của file):

```python
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_query_reads_federation_only(fed_hub, fixture_kb):
    # fixture_kb chứa demo-doc CHƯA publish — không được xuất hiện
    result = runner.invoke(
        app,
        ["query", "restrictive airspace designation",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424 §5.3" in result.output
    assert "demo-doc" not in result.output


def test_query_without_hub_config_errors_with_guide(fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    result = runner.invoke(
        app, ["query", "anything", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 1
    assert "config.yaml" in result.output


def test_query_hub_from_config_file(fed_hub, fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    (fixture_kb / "config.yaml").write_text(f"hub: {fed_hub}\n", encoding="utf-8")
    result = runner.invoke(
        app, ["query", "restrictive airspace", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424" in result.output


def test_get_with_repo_and_l3(fed_hub, fixture_kb):
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--level", "l3", "--repo", "arinc-kb",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "Full raw restrictive airspace" in result.output


def test_get_ambiguous_doc_errors(fed_hub, fixture_kb):
    from tests.conftest import make_fed_entry

    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "dup-kb:arinc-424" in result.output


def test_reindex_repairs_aggregate_index(git_kb, hub_worktree):
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["reindex", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    from center_kb import models

    idx = models.load_yaml_model(
        hub_worktree / "federation" / "index.yaml", models.FederationIndex
    )
    assert [(e.repo_id, e.doc_id) for e in idx.docs] == [("demo-kb", "demo-doc")]


def test_publish_cli_prints_pr_url(git_kb, hub_worktree, monkeypatch):
    from center_kb import publish as publish_mod

    def fake_publish(kb_dir, hub_ref, repo_id=None, mode="auto"):
        return publish_mod.PublishReport(
            repo_id="demo-kb", source_commit="abc1234", n_docs=1,
            pushed=True, mode="pr", pr_url="https://github.com/org/hub/pull/7",
        )

    monkeypatch.setattr(publish_mod, "publish", fake_publish)
    result = runner.invoke(
        app, ["publish", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert "pull/7" in result.output


def test_approve_command_removed(fixture_kb):
    result = runner.invoke(app, ["approve", "demo-doc"])
    assert result.exit_code == 2  # typer: no such command
```

Ghi chú cho `tests/test_cli.py` / `tests/test_cli_context.py` / `tests/test_cli_doctor_diff.py`: giữ các test ingest/summarize/status/build/stats/diff nguyên trạng (không đụng authoring); các test `query`/`get`/`context new`/`resolve`/`doctor` chuyển theo quy tắc (a)/(b) — thêm `--hub str(fed_hub)`, đổi ref thành `arinc-kb:arinc-424 §5.3` (hoặc `arinc-424 §5.3` không qualify khi test auto-qualify), xóa test nào assert đọc local.

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_cli_hub.py -q`

- [ ] **Step 3: Implement trong `src/center_kb/cli.py`:**

3.1. Thay `_resolve_hub_option` bằng:

```python
def _hub_or_exit(hub_flag: str, kb_dir: Path):
    """Hub bắt buộc: flag > env (typer envvar đã fold) > .kb/config.yaml."""
    from center_kb.config import HubConfigError, require_hub
    from center_kb.hub import resolve_hub

    try:
        hub_ref = require_hub(hub_flag, kb_dir)
    except HubConfigError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    handle = resolve_hub(hub_ref)
    if handle is None:
        typer.secho(
            f"could not reach hub '{hub_ref}' and no cache exists — "
            "check the network or the hub path",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if handle.stale:
        age = f"~{handle.age_seconds:.0f}s" if handle.age_seconds else "unknown age"
        typer.secho(
            f"[warn] hub cache is stale ({age})", fg=typer.colors.YELLOW, err=True
        )
    return handle
```

3.2. `query` — thân mới:

```python
    from center_kb.query import search

    handle = _hub_or_exit(hub, kb_dir)
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] or None
    results = search(
        handle, text, tags=tag_list, budget=budget, semantic=semantic
    )
    if not results:
        typer.echo("No matching section found.")
        raise typer.Exit(0)
    for r in results:
        typer.secho(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk", bold=True
        )
        typer.echo(r.content)
        typer.echo("")
```

3.3. `get` — thêm option `repo: str = typer.Option("", "--repo", help="Repo ID khi doc-id trùng giữa các repo")`; thân mới:

```python
    from center_kb.query import AmbiguousDocError, get_section

    handle = _hub_or_exit(hub, kb_dir)
    try:
        result = get_section(handle, doc_id, section, level=level, repo=repo or None)
    except AmbiguousDocError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if result is None:
        typer.secho(f"Not found: {doc_id} §{section}", fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.secho(f"--- [{result.citation}] ~{result.tokens}tk", bold=True)
    typer.echo(result.content)
```

3.4. `publish` — option `hub` đổi default `""` (hết `...` bắt buộc), thêm `--pr/--direct`:

```python
@app.command()
def publish(
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    repo_id: str = typer.Option(
        "", "--repo-id",
        help="Repo ID on the hub (default: config.yaml, rồi tên thư mục git root)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    pr: bool = typer.Option(
        False, "--pr", help="Bắt buộc PR mode (cần gh + hub GitHub)"
    ),
    direct: bool = typer.Option(
        False, "--direct", help="Bắt buộc direct mode (push thẳng main của hub)"
    ),
) -> None:
    """Mirror .kb/ (L0→L3) lên federation/<repo-id>/ của hub + đánh lại index tổng."""
    from center_kb import gitio
    from center_kb import publish as publish_mod
    from center_kb.config import HubConfigError, effective_repo_id, require_hub

    if pr and direct:
        typer.secho("--pr và --direct loại trừ nhau", fg=typer.colors.RED)
        raise typer.Exit(2)
    mode = "pr" if pr else "direct" if direct else "auto"
    try:
        hub_ref = require_hub(hub, kb_dir)
        report = publish_mod.publish(
            kb_dir, hub_ref,
            repo_id=effective_repo_id(repo_id, kb_dir), mode=mode,
        )
    except (HubConfigError, publish_mod.PublishError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
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

Lưu ý test `test_publish_cli_prints_pr_url` monkeypatch `publish_mod.publish` — vì thế thân lệnh phải gọi qua `publish_mod.publish(...)` như trên (không `from ... import publish`).

3.5. `reindex` — lệnh mới (đặt sau `publish`):

```python
@app.command()
def reindex(
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB",
        help="kb-hub URL/path (default: .kb/config.yaml)",
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory (để tìm config)"),
) -> None:
    """Đánh lại federation/index.yaml từ các snapshot con (sửa index lệch)."""
    from center_kb import gitio
    from center_kb.federation import write_federation_index

    handle = _hub_or_exit(hub, kb_dir)
    write_federation_index(handle.federation_dir)
    committed = gitio.commit_paths(
        handle.root, "reindex: rebuild federation/index.yaml", ["federation"]
    )
    if not committed:
        typer.echo("kb reindex: index already consistent — nothing to do")
        return
    if gitio.has_remote(handle.root):
        try:
            gitio.push(handle.root)
        except gitio.GitError as exc:
            typer.secho(
                f"reindex committed but push failed: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
    typer.echo("kb reindex: federation/index.yaml rebuilt")
```

3.6. `context_new`, `resolve`, `doctor` — thay `_resolve_hub_option(hub)` bằng `_hub_or_exit(hub, kb_dir)`; `build_context_block(handle, ref_strs, tags=tag_list)` (bỏ kb_dir); `resolve_refs(handle, ctx)` (bỏ kb_dir); trong `doctor`: `check_context(text, handle)`; repo_id cho `check_hub` lấy `effective_repo_id("", kb_dir) or git_root_name`; bỏ nhánh `if hub:` — hub giờ luôn bắt buộc (`_hub_or_exit` đứng trước `check_kb` vẫn chạy local checks sau khi có handle).

3.7. `build` — xóa khối refresh embeddings (từ `db_path = kb_dir.resolve().parent / ".kb-work" / "embeddings.db"` đến `typer.echo(f"embeddings.db: ...")`): embeddings giờ sống ở hub cache, build lazy lúc query. Xóa test tương ứng trong `tests/test_build.py` nếu có.

3.8. Xóa toàn bộ lệnh `approve` (block `@app.command() def approve(...)`).

- [ ] **Step 4: PASS** — `.venv/bin/python -m pytest tests/test_cli_hub.py tests/test_cli.py tests/test_cli_context.py tests/test_cli_doctor_diff.py tests/test_build.py -q`

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_hub.py tests/test_cli.py tests/test_cli_context.py tests/test_cli_doctor_diff.py tests/test_build.py
git commit -m "feat!: CLI reads only the hub federation; add kb reindex; drop kb approve"
```

---

### Task 12: Gỡ bỏ cơ chế review cũ

**Files:**
- Delete: `src/center_kb/review.py`, `tests/test_review.py`, `tests/test_cli_approve.py`, `.github/workflows/kb-review.yml`, `src/center_kb/templates/init/kb-review.yml`
- Modify: `src/center_kb/initcmd.py` (TEMPLATE_MAP)

**Interfaces:**
- Consumes: Task 11 đã xóa lệnh `approve` (consumer duy nhất của `review.py` ngoài test).
- Produces: không còn đường sinh `status: reviewed` mới; `summarize.redo_reset` vẫn reset được section `reviewed` cũ (không đổi — tương thích dữ liệu cũ).

- [ ] **Step 1: Xóa file**

```bash
git rm src/center_kb/review.py tests/test_review.py tests/test_cli_approve.py
git rm .github/workflows/kb-review.yml src/center_kb/templates/init/kb-review.yml
```

- [ ] **Step 2: Gỡ entry template** — trong `src/center_kb/initcmd.py` xóa dòng:

```python
    ".github/workflows/kb-review.yml": "kb-review.yml",
```

- [ ] **Step 3: Quét tham chiếu sót**

Run: `grep -rn "kb-review\|kb approve\|review.py\|approve_sections\|approve_all_changed" src tests .github scripts --include="*.py" --include="*.yml" --include="*.sh"`
Expected: không còn kết quả nào ngoài chuỗi trong README (xử lý ở Task 15) và `summarize.py` (`redo_reset` nhắc `reviewed` — GIỮ, đó là tương thích dữ liệu cũ).

- [ ] **Step 4: Test import sạch**

Run: `.venv/bin/python -c "import center_kb.cli, center_kb.summarize" && .venv/bin/python -m pytest tests/test_summarize.py tests/test_init.py -q`
Expected: import OK; test_init có thể FAIL vì EXPECTED_FILES còn kb-review.yml trong assert — sửa test đó (xóa dòng kb-review.yml khỏi danh sách expected trong `tests/test_init.py` và `tests/test_templates.py`), chạy lại → PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat!: drop the source-repo review gate (kb approve, kb-review.yml, reviewed status)"
```

---

### Task 13: Web UI + REST API — federation-only

**Files:**
- Rewrite: `src/center_kb/web/api.py` (helpers + routes)
- Modify: `src/center_kb/web/ui.py`
- Modify: `tests/test_web_api.py`, `tests/test_web_ui.py`, `tests/test_web_app.py`

**Interfaces:**
- Consumes: `ServerConfig` mới (hub: str, Task 10), `query.search/get_section/AmbiguousDocError`, `federation.load_federation`.
- Produces:
  - `api.hub_handle(config) -> HubHandle | None` (resolve `config.hub`; None = unreachable → route trả 503).
  - `api.list_docs(config) -> list[dict]` — mỗi dict = IndexEntry.model_dump() + `"repo": <rid>`.
  - `api.load_manifest(config, doc_id, repo: str | None = None) -> tuple[Manifest, str] | None` (raise `AmbiguousDocError`).
  - Routes: `/api/docs`, `/api/docs/{doc}?repo=`, `/api/docs/{doc}/sections/{section}?repo=&level=`, `/api/search`, `/api/health` (thêm `hub_reachable`).
  - UI: mọi link doc/section mang `?repo=<rid>`; mọi section (kể cả repo khác) đều có trang nội dung; scope label = `"hub federation"`.

- [ ] **Step 1: Viết test fail** — trong `tests/test_web_api.py` thay các test list/search/section bằng bản federation (giữ cấu trúc client/app hiện có của file — chỉ đổi fixture + assertions). Test bắt buộc:

```python
def test_health_reports_hub(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    data = client.get("/api/health").json()
    assert data["hub_configured"] is True
    assert data["hub_reachable"] is True


def test_docs_lists_federation_with_repo(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    docs = client.get("/api/docs").json()["docs"]
    assert {(d["repo"], d["id"]) for d in docs} == {
        ("arinc-kb", "arinc-424"), ("icao-kb", "icao-annex-2"),
    }


def test_search_returns_federation_content(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    data = client.get("/api/search", params={"q": "restrictive airspace"}).json()
    assert data["results"][0]["citation"].startswith("arinc-kb:arinc-424")
    assert "Condensed" in data["results"][0]["content"]


def test_section_route_with_repo_param(client_factory, fed_hub):
    client = client_factory(hub=str(fed_hub))
    resp = client.get(
        "/api/docs/arinc-424/sections/5.3", params={"repo": "arinc-kb", "level": "l3"}
    )
    assert resp.status_code == 200
    assert "Full raw" in resp.json()["content"]


def test_ambiguous_doc_returns_400(client_factory, fed_hub):
    from tests.conftest import make_fed_entry

    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    client = client_factory(hub=str(fed_hub))
    resp = client.get("/api/docs/arinc-424/sections/5.3")
    assert resp.status_code == 400
    assert "dup-kb:arinc-424" in resp.json()["detail"]


def test_hub_unreachable_returns_503(client_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    client = client_factory(hub=str(tmp_path / "missing-hub"))
    assert client.get("/api/docs").status_code == 503
```

(`client_factory` = fixture hiện có của file test web dựng app từ `ServerConfig` + token; đổi chữ ký cho nhận `hub=`. Nếu file đang dùng fixture tên khác, giữ tên đó và thêm tham số hub.)

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_web_api.py -q`

- [ ] **Step 3: Rewrite helpers trong `src/center_kb/web/api.py`:**

```python
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from center_kb import models
from center_kb.mcp import ServerConfig
from center_kb.query import AmbiguousDocError, get_section, search

MAX_BUDGET = 20000

HUB_DOWN_DETAIL = (
    "hub unreachable and no local cache — the federation is the only read source"
)


def hub_handle(config: ServerConfig):
    from center_kb.hub import resolve_hub

    return resolve_hub(config.hub)


def _error(status: int, error: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail}, status_code=status)


def list_docs(config: ServerConfig) -> list[dict] | None:
    """None = hub unreachable (caller trả 503)."""
    from center_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None:
        return None
    return [
        {**d.model_dump(), "repo": repo.meta.repo_id}
        for repo in load_federation(hub.federation_dir)
        for d in repo.index.docs
    ]


def known_doc_ids(config: ServerConfig) -> list[str]:
    docs = list_docs(config) or []
    return [f"{d['repo']}:{d['id']}" for d in docs]


def load_manifest(
    config: ServerConfig, doc_id: str, repo: str | None = None
) -> tuple[models.Manifest, str] | None:
    """Tìm manifest trong federation; raise AmbiguousDocError khi trùng doc-id."""
    from center_kb.federation import load_federation

    hub = hub_handle(config)
    if hub is None:
        return None
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    manifest = models.load_yaml_model(
        r.kb_dir / doc_id / "_manifest.yaml", models.Manifest
    )
    return manifest, r.meta.repo_id
```

Routes mới trong `build_routes(config)` (thay các hàm cũ tương ứng):

```python
    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "hub_configured": bool(config.hub),
                "hub_reachable": hub_handle(config) is not None,
            }
        )

    async def docs(request: Request) -> JSONResponse:
        listed = list_docs(config)
        if listed is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        return JSONResponse({"docs": listed})

    async def doc_detail(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        repo = request.query_params.get("repo") or None
        if hub_handle(config) is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            found = load_manifest(config, doc_id, repo=repo)
        except AmbiguousDocError as exc:
            return _error(400, "ambiguous_doc", str(exc))
        if found is None:
            known = ", ".join(known_doc_ids(config))
            return _error(404, "doc_not_found", f"unknown doc '{doc_id}'; known docs: {known}")
        manifest, rid = found
        return JSONResponse(
            {
                "id": manifest.id,
                "title": manifest.title,
                "revision": manifest.revision,
                "repo": rid,
                "sections": [
                    {"id": s.id, "title": s.title, "summary": s.summary, "status": s.status}
                    for s in manifest.sections
                ],
            }
        )

    async def section(request: Request) -> JSONResponse:
        doc_id = request.path_params["doc"]
        section_id = request.path_params["section"]
        repo = request.query_params.get("repo") or None
        level = request.query_params.get("level", "l2")
        if level not in ("l2", "l3"):
            return _error(400, "bad_level", f"level '{level}' is invalid — use 'l2' or 'l3'")
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        try:
            result = get_section(hub, doc_id, section_id, level=level, repo=repo)
        except AmbiguousDocError as exc:
            return _error(400, "ambiguous_doc", str(exc))
        if result is None:
            known = ", ".join(known_doc_ids(config))
            return _error(
                404, "section_not_found",
                f"{doc_id} §{section_id} not found; known docs: {known}",
            )
        return JSONResponse(
            {
                "doc_id": result.doc_id,
                "section_id": result.section_id,
                "title": result.title,
                "citation": result.citation,
                "tokens": result.tokens,
                "level": level,
                "content": result.content,
                "source": result.source,
            }
        )

    async def api_search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "").strip()
        if not q:
            return _error(400, "missing_query", "query parameter 'q' is required")
        raw_tags = request.query_params.get("tags", "")
        tags = [t.strip() for t in raw_tags.split(",") if t.strip()] or None
        try:
            budget = int(request.query_params.get("budget", "2000"))
        except ValueError:
            return _error(400, "bad_budget", "'budget' must be an integer")
        budget = max(1, min(budget, MAX_BUDGET))
        hub = hub_handle(config)
        if hub is None:
            return _error(503, "hub_unreachable", HUB_DOWN_DETAIL)
        results = search(hub, q, tags=tags, budget=budget)
        return JSONResponse(
            {
                "query": q,
                "results": [
                    {
                        "doc_id": r.doc_id,
                        "section_id": r.section_id,
                        "title": r.title,
                        "score": r.score,
                        "citation": r.citation,
                        "tokens": r.tokens,
                        "content": r.content,
                        "source": r.source,
                    }
                    for r in results
                ],
            }
        )
```

- [ ] **Step 4: Cập nhật `src/center_kb/web/ui.py`** — các thay đổi điểm:

1. `home()`: xóa `include_local`; `hub = api.hub_handle(config)`; nếu `hub is None` → `results_html = '<div class="empty-state"><p>Hub unreachable.</p></div>'`; ngược lại `results = search(hub, q, tags=tags or None, budget=2000)`; `docs = api.list_docs(config) or []`; `scope = "hub federation"`.
2. `_result_blocks()`: bỏ nhánh `remote:`; href luôn `f"/ui/docs/{quote(r.doc_id)}/{quote(r.section_id)}?repo={quote(r.source)}"`.
3. `_doc_cards()`: href `f"/ui/docs/{quote(d['id'])}?repo={quote(d['repo'])}"`; badge `_source_badge(d["repo"])`.
4. `_source_badge(source)`: đơn giản hóa — `kind = "repo"`; giữ class css cũ: `f'<span class="source-badge source-remote">{_e(source)}</span>'`.
5. `docs_page()`: `cards = _doc_cards(api.list_docs(config) or [])`.
6. `doc_page()`: `repo = request.query_params.get("repo") or None`; `found = api.load_manifest(config, doc_id, repo=repo)` trong `try/except AmbiguousDocError` → trang 400 liệt kê ứng viên; MỌI section đều là link `f"/ui/docs/{quote(doc_id)}/{quote(s.id)}?repo={quote(rid)}"`; `repo_note = f'<p class="meta">repo: {_e(rid)}</p>'`.
7. `section_page()`: `repo = request.query_params.get("repo") or None`; `result = get_section(api.hub_handle(config), doc_id, section_id, level=level, repo=repo)` (guard hub None → trang 503); toggle href giữ `?level=` và thêm `&repo=`.
8. `tests/test_web_ui.py`: đổi assertions theo — link có `?repo=`, scope text `hub federation`, trang section repo khác trả 200 với nội dung L2. `tests/test_web_app.py`: `ServerConfig(kb_dir=..., hub=str(fed_hub))`.

- [ ] **Step 5: PASS** — `.venv/bin/python -m pytest tests/test_web_api.py tests/test_web_ui.py tests/test_web_app.py -q`

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/web tests/test_web_api.py tests/test_web_ui.py tests/test_web_app.py
git commit -m "feat!: web UI/REST serve the hub federation only, repo-qualified links"
```

---

### Task 14: Scaffold `kb init` — config.yaml, workflow PR-mode, skill/prompt kb-publish

**Files:**
- Create: `src/center_kb/templates/init/config.yaml`
- Modify: `src/center_kb/initcmd.py`, `src/center_kb/templates/init/QUICKSTART.md`
- Rewrite: `src/center_kb/templates/init/claude-skill-kb-publish.md`, `src/center_kb/templates/init/copilot-kb-publish.prompt.md`
- Create template + replace root: `.github/workflows/kb-publish.yml` và `src/center_kb/templates/init/kb-publish.yml` (template MỚI — trước đây workflow này không nằm trong TEMPLATE_MAP)
- Modify: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: CLI surface Task 11.
- Produces: `kb init` scaffold thêm `.kb/config.yaml` (PROTECTED) + `.github/workflows/kb-publish.yml`; không còn scaffold `kb-review.yml`.

- [ ] **Step 1: Template mới.** Tạo `src/center_kb/templates/init/config.yaml`:

```yaml
# CENTER-KB — cấu hình repo (commit vào git).
# hub: URL git hoặc đường dẫn kb-hub — nguồn đọc DUY NHẤT của kb query / MCP / Web UI.
#      Nội dung .kb/ local chỉ tồn tại với người đọc sau khi `kb publish` và PR được merge.
hub: ""
# repo_id: tên repo trên federation (bỏ trống = tên thư mục git root)
repo_id: ""
```

Tạo `src/center_kb/templates/init/kb-publish.yml`:

```yaml
# CI publish snapshot lên kb-hub (PR mode) — chạy khi .kb/ đổi trên main.
# Hub đọc từ .kb/config.yaml (commit trong repo). Secrets cần có:
#   KB_HUB_URL — URL hub kèm token đẩy branch (https://x-access-token:${TOKEN}@github.com/org/kb-hub.git)
#   GH_TOKEN   — token có quyền tạo PR trên repo hub (cho `gh pr create`)
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
      - run: pip install center-kb  # hoặc pip install -e . nếu repo chứa source
      - name: Publish snapshot → PR trên hub
        run: kb publish --hub "${{ secrets.KB_HUB_URL }}" --repo-id "${{ github.event.repository.name }}"
        env:
          GH_TOKEN: ${{ secrets.GH_TOKEN }}
          GIT_AUTHOR_NAME: kb-publish-ci
          GIT_AUTHOR_EMAIL: ci@local
          GIT_COMMITTER_NAME: kb-publish-ci
          GIT_COMMITTER_EMAIL: ci@local
```

Copy nội dung đó đè lên `.github/workflows/kb-publish.yml` của repo này (root và template giữ giống nhau).

- [ ] **Step 2: Rewrite `src/center_kb/templates/init/claude-skill-kb-publish.md`:**

```markdown
---
name: kb-publish
description: Review and publish the local KB to the federation hub — diff vs the published snapshot, confirm, then kb publish (PR on the hub). Use when asked to publish the KB or push knowledge to the hub.
---

# KB Publish — diff → confirm → publish (PR trên hub)

Hub federation là single source of truth: nội dung chỉ search được sau khi
PR publish được merge trên hub. `.kb/` local chỉ là bàn soạn thảo.

<HARD-RULE>
NEVER run `kb publish` until the user has explicitly confirmed, after
seeing the diff, that the current .kb/ state should be published.
</HARD-RULE>

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`, or the
   kb-summarize skill).
2. **Show what will be published.** Run `kb doctor` — it reports whether
   local .kb differs from the published snapshot. For each doc with
   changes, run `kb diff <doc-id> --against HEAD` (use another git rev if
   the user names one) and present the added/changed sections.
3. **Confirm — the gate.** State the hub (from `.kb/config.yaml`, or
   `CENTER_KB_HUB` if set) and that a publish PR will be opened on it
   (local-path hub → direct push). Ask for one explicit go/no-go and wait.
4. **Execute** (only after confirmation): `kb publish`. Relay the result:
   repo-id, source commit, doc count, and the **PR URL** — remind the user
   the content goes live when that PR is merged on the hub.
5. **Errors.**
   - Missing hub config → tell the user to fill `hub:` in `.kb/config.yaml`.
   - `gh` missing in PR mode → install GitHub CLI, or `kb publish --direct`
     only if direct pushes are allowed for this hub.
   - Other git/hub errors → show the stderr and suggest `kb doctor`.
```

`src/center_kb/templates/init/copilot-kb-publish.prompt.md`: thay bằng cùng nội dung workflow (mục 1–5 y hệt), giữ đúng format frontmatter/heading hiện có của file copilot prompt (xem file cũ trước khi thay — chỉ đổi phần thân).

- [ ] **Step 3: `initcmd.py`** — trong `TEMPLATE_MAP` thêm 2 entry, entry kb-review đã xóa ở Task 12:

```python
    ".kb/config.yaml": "config.yaml",
    ".github/workflows/kb-publish.yml": "kb-publish.yml",
```

Thêm vào `PROTECTED_FILES`:

```python
PROTECTED_FILES: frozenset[str] = frozenset({".kb/index.yaml", ".kb/config.yaml"})
```

- [ ] **Step 4: `QUICKSTART.md` template** — chèn sau phần init (trước phần ingest) khối:

```markdown
## Kết nối hub (bắt buộc)

Điền `hub:` trong `.kb/config.yaml` (URL git hoặc đường dẫn kb-hub) và commit.
`kb query` / MCP / Web UI CHỈ đọc từ federation của hub — nội dung mới chỉ
xuất hiện sau khi `kb publish` và PR được merge trên hub.
```

- [ ] **Step 5: Test** — trong `tests/test_init.py` + `tests/test_templates.py`: cập nhật danh sách file expected (thêm `.kb/config.yaml`, `.github/workflows/kb-publish.yml`; bỏ `.github/workflows/kb-review.yml`); thêm test protected:

```python
def test_init_does_not_overwrite_config(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path)
    cfg = tmp_path / ".kb" / "config.yaml"
    cfg.write_text("hub: /my/hub\n", encoding="utf-8")
    report = init_repo(tmp_path)
    assert ".kb/config.yaml" in report.skipped
    assert cfg.read_text(encoding="utf-8") == "hub: /my/hub\n"
```

Run: `.venv/bin/python -m pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: scaffold .kb/config.yaml + PR-mode kb-publish workflow; new publish skill"
```

---

### Task 15: E2E mới, demo script, README + migration, version bump, full gate

**Files:**
- Create: `tests/test_federation_e2e.py`
- Delete: `tests/test_phase2_e2e.py`, `tests/test_phase3_e2e.py`
- Rewrite: `scripts/demo-federation.sh`
- Modify: `README.md`, `pyproject.toml` (version `0.9.0`)

**Interfaces:** Consumes toàn bộ Task 1–14. Không produces gì mới.

- [ ] **Step 1: E2E test** — tạo `tests/test_federation_e2e.py`:

```python
"""E2E: vòng đời publish-first — hub federation là single source of truth."""
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app

runner = CliRunner()


def _make_repo(base: Path, run_git, name: str, doc_id: str, sec_id: str, keyword: str, hub: Path) -> Path:
    root = base / name
    kb = root / ".kb"
    doc = kb / doc_id
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text(
        f"## {sec_id} Title\n\nCondensed {keyword} content.\n", encoding="utf-8"
    )
    (doc / "ch1.raw.md").write_text(
        f"## {sec_id} Title\n\nVerbatim {keyword} content.\n", encoding="utf-8"
    )
    models.save_yaml_model(
        doc / "_manifest.yaml",
        models.Manifest(
            id=doc_id, title=doc_id,
            sections=[models.SectionEntry(
                id=sec_id, title="Title", summary=f"{keyword} summary.",
                status="summarized", file="ch1",
            )],
        ),
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id=doc_id, title=doc_id, tags=[name], summary=f"{keyword} doc.",
        )]),
    )
    (kb / "config.yaml").write_text(
        f"hub: {hub}\nrepo_id: {name}\n", encoding="utf-8"
    )
    run_git(root, "init")
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")
    return root


def _make_hub(base: Path, run_git) -> Path:
    hub = base / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    (hub / "federation").mkdir()
    (hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "t")
    run_git(hub, "config", "user.email", "t@t")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v0")
    return hub


def test_full_lifecycle(tmp_path, run_git):
    hub = _make_hub(tmp_path, run_git)
    repo_a = _make_repo(tmp_path, run_git, "repo-alpha", "alpha-spec", "1.1", "alpha widget", hub)
    repo_b = _make_repo(tmp_path, run_git, "repo-beta", "beta-spec", "2.1", "beta gadget", hub)

    # 1) publish cả 2 repo (direct — hub local-path); hub config đọc từ .kb/config.yaml
    for repo in (repo_a, repo_b):
        r = runner.invoke(app, ["publish", "--kb-dir", str(repo / ".kb")])
        assert r.exit_code == 0, r.output

    # 2) index tổng có đủ 2 repo
    idx = models.load_yaml_model(hub / "federation" / "index.yaml", models.FederationIndex)
    assert {(e.repo_id, e.doc_id) for e in idx.docs} == {
        ("repo-alpha", "alpha-spec"), ("repo-beta", "beta-spec"),
    }

    # 3) search cross-repo từ repo A ra doc của repo B, full L2
    r = runner.invoke(app, ["query", "beta gadget", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    assert "repo-beta:beta-spec §2.1" in r.output
    assert "Condensed beta gadget" in r.output

    # 4) get L3 verbatim qua hub
    r = runner.invoke(
        app, ["get", "beta-spec", "2.1", "--level", "l3", "--kb-dir", str(repo_a / ".kb")]
    )
    assert r.exit_code == 0, r.output
    assert "Verbatim beta gadget" in r.output

    # 5) context new pin HEAD hub + ref auto-qualified; resolve ok
    r = runner.invoke(
        app,
        ["context", "new", "--refs", "beta-spec §2.1", "--kb-dir", str(repo_a / ".kb")],
    )
    assert r.exit_code == 0, r.output
    block = r.output
    assert "- repo-beta:beta-spec §2.1" in block
    hub_head = run_git(hub, "rev-parse", "--short", "HEAD")
    assert f'version: "{hub_head}"' in block

    ticket = tmp_path / "ticket.md"
    ticket.write_text(block, encoding="utf-8")
    r = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    assert "status=ok" in r.output

    # 6) amend repo B + republish → resolve stale (exit 2)
    l2 = repo_b / ".kb" / "beta-spec" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("Condensed beta", "Condensed AMENDED beta"),
        encoding="utf-8",
    )
    run_git(repo_b, "add", "-A")
    run_git(repo_b, "commit", "-m", "amendment")
    r = runner.invoke(app, ["publish", "--kb-dir", str(repo_b / ".kb")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 2, r.output
    assert "stale" in r.output

    # 7) doctor bắt index lệch, reindex sửa
    (hub / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    r = runner.invoke(app, ["doctor", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 1
    assert "kb reindex" in r.output
    r = runner.invoke(app, ["reindex", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["doctor", "--kb-dir", str(repo_a / ".kb")])
    assert r.exit_code == 0, r.output
```

Run: `.venv/bin/python -m pytest tests/test_federation_e2e.py -q` → PASS. Rồi:

```bash
git rm tests/test_phase2_e2e.py tests/test_phase3_e2e.py
```

(vòng authoring ingest→summarize→build đã có `tests/test_summarize_e2e.py` phủ.)

- [ ] **Step 2: Rewrite `scripts/demo-federation.sh`:**

```bash
#!/usr/bin/env bash
# Demo: hub federation = single source of truth.
# Dựng kb-hub + 2 repo con trong thư mục tạm, publish (direct mode),
# search cross-repo, citation pin, stale sau amendment. Tự dọn dẹp.
set -euo pipefail

DEMO_DIR="$(mktemp -d)"
trap 'rm -rf "$DEMO_DIR"' EXIT
export CENTER_KB_HUB_CACHE="$DEMO_DIR/.hub-cache"
G() { git -C "$1" -c user.name=demo -c user.email=demo@local -c core.excludesFile= "${@:2}"; }

echo "== 1. Dựng kb-hub =="
HUB="$DEMO_DIR/kb-hub"
mkdir -p "$HUB/.kb" "$HUB/federation"
printf 'docs: []\n' > "$HUB/.kb/index.yaml"
touch "$HUB/federation/.gitkeep"
git init -q "$HUB"; G "$HUB" add -A; G "$HUB" commit -qm "hub v0"

make_repo() { # $1=name $2=doc $3=sec $4=keyword
  local ROOT="$DEMO_DIR/$1" DOC="$DEMO_DIR/$1/.kb/$2"
  mkdir -p "$DOC"
  printf '## %s Title\n\nCondensed %s content.\n' "$3" "$4" > "$DOC/ch1.md"
  printf '## %s Title\n\nVerbatim %s content.\n' "$3" "$4" > "$DOC/ch1.raw.md"
  cat > "$DOC/_manifest.yaml" <<EOF
id: $2
title: $2
sections:
  - id: '$3'
    title: Title
    summary: $4 summary.
    status: summarized
    file: ch1
EOF
  cat > "$DEMO_DIR/$1/.kb/index.yaml" <<EOF
docs:
  - id: $2
    title: $2
    tags: [$1]
    summary: $4 doc.
EOF
  printf 'hub: %s\nrepo_id: %s\n' "$HUB" "$1" > "$DEMO_DIR/$1/.kb/config.yaml"
  git init -q "$ROOT"; G "$ROOT" add -A; G "$ROOT" commit -qm "v1"
}

echo "== 2. Dựng 2 repo con =="
make_repo repo-alpha alpha-spec 1.1 "alpha widget"
make_repo repo-beta  beta-spec  2.1 "beta gadget"

echo "== 3. Publish cả hai (direct mode — hub local path) =="
kb publish --kb-dir "$DEMO_DIR/repo-alpha/.kb"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"

echo "== 4. Index tổng trên hub =="
cat "$HUB/federation/index.yaml"

echo "== 5. Search cross-repo từ repo-alpha (chỉ đọc federation) =="
kb query "beta gadget" --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 6. L3 verbatim qua hub =="
kb get beta-spec 2.1 --level l3 --kb-dir "$DEMO_DIR/repo-alpha/.kb"

echo "== 7. Pin citation tại HEAD hub =="
kb context new --refs "beta-spec §2.1" --kb-dir "$DEMO_DIR/repo-alpha/.kb" | tee "$DEMO_DIR/ticket.md"

echo "== 8. Amendment ở repo-beta + republish → citation stale =="
sed -i.bak 's/Condensed beta/Condensed AMENDED beta/' "$DEMO_DIR/repo-beta/.kb/beta-spec/ch1.md"
G "$DEMO_DIR/repo-beta" add -A; G "$DEMO_DIR/repo-beta" commit -qm "amendment"
kb publish --kb-dir "$DEMO_DIR/repo-beta/.kb"
kb resolve "$DEMO_DIR/ticket.md" --kb-dir "$DEMO_DIR/repo-alpha/.kb" || true

echo "== Demo hoàn tất — hub federation là nguồn đọc duy nhất =="
```

Run: `bash scripts/demo-federation.sh` (cần `kb` trong PATH của venv: `source .venv/bin/activate` trước) — script chạy hết, thấy citation stale ở bước 8.

- [ ] **Step 3: README** — các sửa đổi:

1. §7.9 (Phase 3 federation): thay mô tả "L0+L1 snapshot / local wins" bằng đoạn:

```markdown
> **Kiến trúc hub-first (2026-07-13):** `kb query`, MCP và Web UI **chỉ đọc
> `federation/` của hub** — `.kb/` local là bàn soạn thảo, không ai query vào.
> `kb publish` mirror đầy đủ L0→L3 vào `federation/<repo-id>/`, đánh lại index
> tổng `federation/index.yaml`, và (với hub GitHub) mở PR — merge PR là cổng
> review duy nhất, nội dung chỉ search được sau khi merge. Chi tiết:
> `docs/superpowers/specs/2026-07-13-hub-federation-single-source-design.md`.
```

2. Bảng lệnh: xóa dòng `kb approve`; sửa mô tả `kb query` thành "Natural-language question → relevant passages **from the hub federation** (hub bắt buộc — `.kb/config.yaml`)"; sửa `kb publish` thành "Mirror .kb/ (L0→L3) → PR trên hub (direct với hub local-path)"; thêm dòng `| … | kb reindex | Đánh lại federation/index.yaml khi lệch | Sửa chữa |`.
3. Xóa ghi chú "reviewed status on the hub lags one beat" (không còn kb-review).
4. Thêm mục **Migration** (chèn trước phần footnote cuối):

```markdown
## Migration sang kiến trúc hub-first (v0.9.0)

1. Nâng cấp CLI mọi nơi (`pip install -U center-kb`) — không chạy song song 2 version.
2. Mỗi repo: thêm `.kb/config.yaml` (`hub:` + `repo_id:`), xóa
   `.github/workflows/kb-review.yml`, thay `kb-publish.yml` bằng template mới
   (`kb init` làm cả ba việc này).
3. Mỗi repo (kể cả hub): chạy `kb publish` một lần — entry federation format cũ
   được thay bằng mirror đầy đủ, index tổng hình thành.
4. Hub GitHub: bật branch protection cho `main` (*require PR* + *require
   branches up to date*).
5. Ticket có block `kb-context` cũ (pin commit repo local): `kb_resolve` sẽ báo
   `broken` kèm hint — re-pin bằng `kb_context_new` khi chạm vào ticket đó.
```

5. Cập nhật footnote cuối README: thêm spec 2026-07-13 vào danh sách.

- [ ] **Step 4: Version bump** — trong `pyproject.toml`: `version = "0.8.0"` → `version = "0.9.0"`.

- [ ] **Step 5: Full gate**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
```

Expected: tất cả xanh. Nếu mypy kêu về signature cũ còn sót ở file chưa kể tên — sửa call site theo Interfaces của task tương ứng (không thay đổi thiết kế).

- [ ] **Step 6: Commit cuối**

```bash
git add -A
git commit -m "feat!: hub federation is the single source of truth (v0.9.0)

- kb query / MCP / Web UI read only federation/ on the hub
- publish mirrors full L0-L3 + regenerates federation/index.yaml
- PR on the hub is the single review gate; kb approve removed
- kb-context pins one hub HEAD commit, refs repo-qualified
- new: .kb/config.yaml (mandatory hub), kb reindex, gh-based PR publish"
```

---

## Ghi chú self-review (đã soát khi viết plan)

- **Spec coverage:** tiêu chí 1 → Task 6/10/11/13; tiêu chí 2 → Task 5 (+ test l3 Task 6/15); tiêu chí 3 → Task 3/5/9/11; tiêu chí 4 → Task 5/11/14; tiêu chí 5 → Task 7/8; tiêu chí 6 → Task 1/10/11/13. Migration/README → Task 15. Bỏ review → Task 11/12.
- **Type consistency:** `search(hub, text, tags, budget, semantic, embedder)`; `get_section(hub, doc_id, section_id, level, repo)`; `build_context_block(hub, refs, tags) -> (str, str|None)`; `resolve_refs(hub, ctx)`; `check_hub(kb_dir, handle, repo_id)`; `check_context(text, hub)`; `publish(kb_dir, hub_ref, repo_id, max_retries, mode)`; `ServerConfig(kb_dir, hub: str, ...)` — mọi task dùng đúng các chữ ký này.
- **Điểm dễ vấp cho người thực thi:**
  1. PR mode PHẢI `checkout` về branch gốc trong `finally` — hub cache dùng chung cho query; bỏ sót là search đọc nhầm branch publish.
  2. `commit_paths` giới hạn `["federation"]` — không được `git add -A` trên hub (dính `.kb-work/` embeddings).
  3. BM25 test: hai doc trong `fed_hub` cùng chứa token "airspace" — khi assert thứ hạng, dùng query có token đặc thù ("restrictive").
  4. Máy dev có `gh`/`claude` thật: mọi test liên quan PHẢI monkeypatch `ghio.gh_available` (kể cả test auto-mode) — đã thể hiện trong test Task 5.
  5. `hub_worktree` fixture cũ vẫn dùng cho publish/doctor test (hub direct-path); `fed_hub` cho query/context/resolve/mcp/web.

