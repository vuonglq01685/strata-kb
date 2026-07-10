# AERO-KB Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đóng vòng BA → Jira → Dev: MCP server stdio (3 tool), block `kb-context` chuẩn hóa, resolve theo version pin, `kb diff`, `kb doctor`, heading pattern thành config.

**Architecture:** Mọi thứ mới là adapter quanh tầng query hiện có (`query.py`). 6 module mới trong `src/aero_kb/`: `gitio` (đọc file tại git rev — chỗ duy nhất chạy subprocess git), `kbcontext` (schema + parse block), `resolve` (pin version + freshness), `diff`, `doctor`, `mcp` (server). Phụ thuộc một chiều: `mcp.py`/`cli.py` gọi xuống engine, engine không import ngược lên.

**Tech Stack:** Python ≥3.11, Typer, pydantic v2, PyYAML, rank-bm25, tiktoken, official MCP Python SDK (`mcp` package, v2 API: `from mcp.server import MCPServer`), pytest + anyio.

**Spec:** `docs/superpowers/specs/2026-07-10-aero-kb-phase2-design.md` — đọc trước khi làm.

## Global Constraints

- Python `>=3.11`; type annotation trên mọi signature; PEP 8.
- **Engine thuần:** `src/aero_kb/` không hardcode tri thức ARINC/Annex; heading convention chỉ tồn tại dạng config default trung tính.
- **Content thuần:** `.kb/` không chứa logic; config ingest per-doc nằm trong `_manifest.yaml`.
- **MCP stdio:** stdout thuộc về protocol — trong `mcp.py` KHÔNG dùng `print()`; log qua `logging` (mặc định ra stderr).
- Dependency mới duy nhất: `mcp>=2.0` (main), `anyio>=4.0` (dev). Không thêm gì khác.
- `--hub` được parse vào `ServerConfig.hub` nhưng KHÔNG kích hoạt logic nào (chỉ log cảnh báo) — Phase 3 mới dùng.
- Help text CLI + message lỗi bằng tiếng Việt (theo style `cli.py` hiện có); message lỗi domain luôn kèm gợi ý khắc phục.
- Commit message: `<type>: <mô tả tiếng Việt>` như history hiện có (`git log --oneline`), không có attribution footer.
- Chạy test: `source .venv/bin/activate` trước (venv python3.13 có sẵn ở root repo).

## File Structure (toàn Phase 2)

```
src/aero_kb/
├── gitio.py        # Task 1 — git helpers (subprocess duy nhất ở đây)
├── kbcontext.py    # Task 2 — KBRef/KBContext, parse/render block
├── resolve.py      # Task 3 — resolve_refs + render_resolved
├── diff.py         # Task 4 — diff_doc + render_diff
├── doctor.py       # Task 5 — check_kb + check_context
├── cli.py          # Task 6+7 — thêm: context new, resolve, diff, doctor
├── models.py       # Task 8 — thêm IngestConfig, Manifest.ingest
├── ingest/
│   ├── sectioner.py  # Task 8 — HeadingConfig, bỏ hằng số regex
│   ├── parser.py     # Task 8 — bookmark_ids nhận config
│   └── scaffold.py   # Task 8 — persist ingest config vào manifest
├── mcp.py          # Task 9 — MCP server (3 tool, --kb/--hub)
tests/
├── conftest.py     # Task 1 — thêm fixture run_git, git_kb
├── test_gitio.py test_kbcontext.py test_resolve.py test_diff.py
├── test_doctor.py test_cli_context.py test_cli_doctor_diff.py
├── test_heading_config.py test_mcp.py test_phase2_e2e.py
.mcp.json           # Task 9
pyproject.toml      # Task 9 — deps
```

---

### Task 1: `gitio.py` — đọc file tại một git rev

**Files:**
- Create: `src/aero_kb/gitio.py`
- Modify: `tests/conftest.py` (thêm fixture `run_git`, `git_kb` — dùng cho Task 3, 4, 5, 7, 10)
- Test: `tests/test_gitio.py`

**Interfaces:**
- Consumes: không gì từ task khác.
- Produces (Task 3/4/5/6 dùng):
  - `class GitError(RuntimeError)`
  - `git_root(start: Path) -> Path` — raise `GitError` nếu không nằm trong repo
  - `head_commit(root: Path) -> str` — short hash HEAD
  - `rev_exists(root: Path, rev: str) -> bool`
  - `read_at(root: Path, rev: str, path: Path) -> str | None` — None nếu file không tồn tại ở rev; raise `GitError` nếu rev không tồn tại hoặc path nằm ngoài repo
  - `is_dirty(root: Path, subpath: Path) -> bool`

- [ ] **Step 1: Thêm fixture git vào `tests/conftest.py`** (append vào cuối file, thêm `import subprocess` lên đầu)

```python
@pytest.fixture
def run_git():
    """Callable chạy git trong một thư mục, identity cố định cho test."""

    def _run(root: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", "-c", "user.name=test", "-c", "user.email=test@test.local", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    return _run


@pytest.fixture
def git_kb(fixture_kb: Path, run_git) -> dict:
    """Git repo chứa .kb/ với 2 commit — mô phỏng amendment.

    Commit 1 (rev1): KB như fixture_kb — thời điểm BA viết requirement.
    Commit 2 (rev2 = HEAD): §1.1 đổi nội dung L2 + summary (amendment đã merge).
    Trả về: {"root", "kb", "rev1", "rev2"}.
    """
    root = fixture_kb.parent
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v1")
    rev1 = run_git(root, "rev-parse", "--short", "HEAD")

    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airspace record structure with designation and type fields.",
            "airspace record structure with NEW multiple code field.",
        ),
        encoding="utf-8",
    )
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = (
        "Airspace record structure: designation, type, multiple code."
    )
    models.save_yaml_model(manifest_path, manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v2 - amendment 1.1")
    rev2 = run_git(root, "rev-parse", "--short", "HEAD")
    return {"root": root, "kb": fixture_kb, "rev1": rev1, "rev2": rev2}
```

- [ ] **Step 2: Viết test fail** — `tests/test_gitio.py`

```python
from pathlib import Path

import pytest

from aero_kb import gitio


def test_git_root_finds_repo_from_kb_dir(git_kb):
    assert gitio.git_root(git_kb["kb"]) == git_kb["root"]


def test_git_root_raises_outside_repo(tmp_path: Path):
    with pytest.raises(gitio.GitError):
        gitio.git_root(tmp_path)


def test_head_commit_returns_short_hash(git_kb):
    assert gitio.head_commit(git_kb["root"]) == git_kb["rev2"]


def test_rev_exists(git_kb):
    assert gitio.rev_exists(git_kb["root"], git_kb["rev1"])
    assert not gitio.rev_exists(git_kb["root"], "deadbeef")


def test_read_at_returns_old_content(git_kb):
    path = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    old = gitio.read_at(git_kb["root"], git_kb["rev1"], path)
    assert "designation and type fields" in old
    new = gitio.read_at(git_kb["root"], git_kb["rev2"], path)
    assert "NEW multiple code field" in new


def test_read_at_missing_file_returns_none(git_kb):
    path = git_kb["kb"] / "demo-doc" / "khong-ton-tai.md"
    assert gitio.read_at(git_kb["root"], git_kb["rev1"], path) is None


def test_read_at_bad_rev_raises(git_kb):
    path = git_kb["kb"] / "index.yaml"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], "deadbeef", path)


def test_read_at_path_outside_repo_raises(git_kb, tmp_path_factory):
    outside = tmp_path_factory.mktemp("ngoai") / "x.md"
    with pytest.raises(gitio.GitError):
        gitio.read_at(git_kb["root"], git_kb["rev1"], outside)


def test_is_dirty(git_kb):
    assert not gitio.is_dirty(git_kb["root"], git_kb["kb"])
    (git_kb["kb"] / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    assert gitio.is_dirty(git_kb["root"], git_kb["kb"])
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `pytest tests/test_gitio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.gitio'`

- [ ] **Step 4: Implement `src/aero_kb/gitio.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    """Lỗi khi gọi git: không phải repo, rev không tồn tại, path ngoài repo."""


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True
    )


def git_root(start: Path) -> Path:
    cwd = start if start.is_dir() else start.parent
    proc = _run(cwd, "rev-parse", "--show-toplevel")
    if proc.returncode != 0:
        raise GitError(
            f"'{start}' không nằm trong git repo — resolve/diff/doctor --context cần KB được version bằng Git"
        )
    return Path(proc.stdout.strip()).resolve()


def head_commit(root: Path) -> str:
    proc = _run(root, "rev-parse", "--short", "HEAD")
    if proc.returncode != 0:
        raise GitError(f"không lấy được HEAD: {proc.stderr.strip()}")
    return proc.stdout.strip()


def rev_exists(root: Path, rev: str) -> bool:
    proc = _run(root, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}")
    return proc.returncode == 0


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise GitError(f"'{path}' nằm ngoài git repo '{root}'") from exc


def read_at(root: Path, rev: str, path: Path) -> str | None:
    """Nội dung file tại một rev; None nếu file không tồn tại ở rev đó.

    Raise GitError nếu rev không tồn tại (phân biệt với file thiếu —
    git show trả cùng exit code cho cả hai).
    """
    rel = _relpath(root, path)
    if not rev_exists(root, rev):
        raise GitError(f"rev '{rev}' không tồn tại trong repo (force-push hoặc shallow clone?)")
    proc = _run(root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout


def is_dirty(root: Path, subpath: Path) -> bool:
    rel = _relpath(root, subpath)
    proc = _run(root, "status", "--porcelain", "--", rel)
    return bool(proc.stdout.strip())
```

- [ ] **Step 5: Chạy test, xác nhận pass**

Run: `pytest tests/test_gitio.py -v`
Expected: 9 PASS

- [ ] **Step 6: Chạy toàn bộ suite, commit**

Run: `pytest -q` — Expected: tất cả pass.

```bash
git add src/aero_kb/gitio.py tests/test_gitio.py tests/conftest.py
git commit -m "feat: gitio — đọc file .kb tại git rev, nền cho resolve/diff/doctor"
```

---

### Task 2: `kbcontext.py` — schema + parse/render block kb-context

**Files:**
- Create: `src/aero_kb/kbcontext.py`
- Test: `tests/test_kbcontext.py`

**Interfaces:**
- Consumes: không gì từ task khác.
- Produces (Task 3/5/6/9 dùng):
  - `class KBContextError(ValueError)`
  - `class KBRef(BaseModel)`: `doc_id: str`, `section_id: str`, `__str__` → `"arinc-424 §5.3"`
  - `class KBContext(BaseModel)`: `version: str`, `refs: list[KBRef]`, `tags: list[str] = []`
  - `parse_ref(text: str) -> KBRef` — nhận `"doc §5.3"` và `"doc 5.3"`; raise `KBContextError` nếu sai
  - `parse(text: str) -> KBContext` — nhận block YAML thuần HOẶC nguyên văn ticket chứa block; raise `KBContextError`
  - `render(ctx: KBContext) -> str` — block YAML chuẩn (dạng có `§`)

- [ ] **Step 1: Viết test fail** — `tests/test_kbcontext.py`

```python
import pytest

from aero_kb import kbcontext

BLOCK = """kb-context:
  version: a3f9c21
  refs:
    - arinc-424 §5.3
    - arinc-424 §5.3.2
  tags: [arinc424, airspace]
"""

TICKET = f"""# TAL-1580 — Hiển thị pop-up Restrictive Airspace

Là một dispatcher, tôi muốn click vào restrictive airspace.

Acceptance criteria:
- Hiển thị field P1 [arinc-424 §5.3]

{BLOCK}
Ghi chú thêm sau block.
"""


def test_parse_ref_standard():
    ref = kbcontext.parse_ref("arinc-424 §5.3")
    assert ref.doc_id == "arinc-424"
    assert ref.section_id == "5.3"
    assert str(ref) == "arinc-424 §5.3"


def test_parse_ref_without_section_mark():
    ref = kbcontext.parse_ref("arinc-424 5.3.2")
    assert ref.section_id == "5.3.2"


def test_parse_ref_invalid_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="§"):
        kbcontext.parse_ref("chỉ-có-doc-id")


def test_parse_pure_block():
    ctx = kbcontext.parse(BLOCK)
    assert ctx.version == "a3f9c21"
    assert [str(r) for r in ctx.refs] == ["arinc-424 §5.3", "arinc-424 §5.3.2"]
    assert ctx.tags == ["arinc424", "airspace"]


def test_parse_block_embedded_in_ticket():
    ctx = kbcontext.parse(TICKET)
    assert ctx.version == "a3f9c21"
    assert len(ctx.refs) == 2


def test_parse_missing_block_raises():
    with pytest.raises(kbcontext.KBContextError, match="kb-context"):
        kbcontext.parse("ticket không có block nào")


def test_parse_missing_version_raises():
    with pytest.raises(kbcontext.KBContextError, match="version"):
        kbcontext.parse("kb-context:\n  refs:\n    - a §1\n")


def test_parse_missing_refs_raises():
    with pytest.raises(kbcontext.KBContextError, match="refs"):
        kbcontext.parse("kb-context:\n  version: abc1234\n")


def test_render_roundtrip():
    ctx = kbcontext.parse(BLOCK)
    rendered = kbcontext.render(ctx)
    assert kbcontext.parse(rendered) == ctx
    assert "§5.3" in rendered
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_kbcontext.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.kbcontext'`

- [ ] **Step 3: Implement `src/aero_kb/kbcontext.py`**

```python
from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field


class KBContextError(ValueError):
    """Block kb-context thiếu hoặc sai format."""


class KBRef(BaseModel):
    doc_id: str
    section_id: str

    def __str__(self) -> str:
        return f"{self.doc_id} §{self.section_id}"


class KBContext(BaseModel):
    version: str
    refs: list[KBRef]
    tags: list[str] = Field(default_factory=list)


_REF_RE = re.compile(r"^(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s+§?(?P<sec>\S+)$")
_KEY_RE = re.compile(r"^(?P<indent>\s*)kb-context:\s*$")


def parse_ref(text: str) -> KBRef:
    m = _REF_RE.match(" ".join(text.split()))
    if not m:
        raise KBContextError(
            f"ref '{text}' sai format — cần '<doc-id> §<section-id>', vd 'arinc-424 §5.3'"
        )
    return KBRef(doc_id=m.group("doc"), section_id=m.group("sec"))


def _extract_block(text: str) -> str:
    """Cắt block kb-context đầu tiên theo indent — chấp nhận block lẫn trong ticket."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = _KEY_RE.match(line)
        if not m:
            continue
        indent = len(m.group("indent"))
        block = [line[indent:]]
        for follow in lines[i + 1 :]:
            if not follow.strip():
                block.append("")
                continue
            cur = len(follow) - len(follow.lstrip())
            if cur <= indent:
                break
            block.append(follow[indent:])
        return "\n".join(block)
    raise KBContextError("không tìm thấy block 'kb-context:' trong text")


def parse(text: str) -> KBContext:
    block = _extract_block(text)
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise KBContextError(f"block kb-context không phải YAML hợp lệ: {exc}") from exc
    payload = (data or {}).get("kb-context")
    if not isinstance(payload, dict):
        raise KBContextError("block kb-context rỗng hoặc sai cấu trúc")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise KBContextError("kb-context thiếu 'version' (commit hash lúc BA viết)")
    raw_refs = payload.get("refs") or []
    if not raw_refs:
        raise KBContextError("kb-context thiếu 'refs' — phải cite ít nhất 1 section")
    refs = [parse_ref(str(r)) for r in raw_refs]
    tags = [str(t) for t in (payload.get("tags") or [])]
    return KBContext(version=version, refs=refs, tags=tags)


def render(ctx: KBContext) -> str:
    lines = ["kb-context:", f"  version: {ctx.version}", "  refs:"]
    lines += [f"    - {ref}" for ref in ctx.refs]
    if ctx.tags:
        lines.append(f"  tags: [{', '.join(ctx.tags)}]")
    return "\n".join(lines)
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_kbcontext.py -v`
Expected: 9 PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/kbcontext.py tests/test_kbcontext.py
git commit -m "feat: kbcontext — schema + parse/render block kb-context"
```

---

### Task 3: `resolve.py` — resolve refs theo version pin + freshness

**Files:**
- Create: `src/aero_kb/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: `gitio.git_root/read_at/GitError` (Task 1); `kbcontext.KBContext/KBRef` (Task 2); `models.Manifest`, `mdutils.slice_section/count_tokens`, citation format `"<doc> §<sec> (<revision>)"` như `query._citation`.
- Produces (Task 5/6/9 dùng):
  - `Status = Literal["ok", "stale", "broken"]`
  - `@dataclass ResolvedRef`: `ref: KBRef`, `status: Status`, `citation: str`, `content: str`, `tokens: int`, `reason: str = ""`
  - `resolve_refs(kb_dir: Path, ctx: KBContext) -> list[ResolvedRef]` — raise `GitError` nếu kb_dir không trong repo; lỗi từng ref KHÔNG raise, thành `status="broken"`
  - `render_resolved(results: list[ResolvedRef], version: str) -> str`

**Ngữ nghĩa freshness (theo spec §6, đã làm rõ):** `broken` = không resolve được TẠI REV PIN (doc/section không tồn tại ở rev, rev không tồn tại). `stale` = resolve được ở pin nhưng nội dung L2 ở worktree khác (hoặc section đã biến mất khỏi worktree). So sánh sau khi `.strip()`.

- [ ] **Step 1: Viết test fail** — `tests/test_resolve.py`

```python
from aero_kb import kbcontext
from aero_kb.resolve import render_resolved, resolve_refs


def _ctx(version: str, *refs: str) -> kbcontext.KBContext:
    return kbcontext.KBContext(
        version=version, refs=[kbcontext.parse_ref(r) for r in refs]
    )


def test_ok_when_section_unchanged(git_kb):
    # §1.2 không đổi giữa rev1 và worktree
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.2"))
    assert results[0].status == "ok"
    assert "Airway Records" in results[0].content
    assert results[0].citation == "demo-doc §1.2 (Rev 1)"
    assert results[0].tokens > 0


def test_stale_returns_pinned_content(git_kb):
    # §1.1 đã đổi sau rev1 — trả nội dung TẠI BẢN PIN, không phải bản mới
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1"))
    assert results[0].status == "stale"
    assert "designation and type fields" in results[0].content
    assert "NEW multiple code" not in results[0].content
    assert results[0].reason


def test_pin_at_head_is_ok(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.1"))
    assert results[0].status == "ok"


def test_broken_unknown_section(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §9.9"))
    assert results[0].status == "broken"
    assert "9.9" in results[0].reason


def test_broken_unknown_doc(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "khong-co §1.1"))
    assert results[0].status == "broken"


def test_broken_bad_rev_does_not_break_batch(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx("deadbeef", "demo-doc §1.1", "demo-doc §1.2")
    )
    assert [r.status for r in results] == ["broken", "broken"]
    assert "deadbeef" in results[0].reason


def test_render_resolved_marks_status(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1", "demo-doc §1.2")
    )
    text = render_resolved(results, git_kb["rev1"])
    assert f"@ {git_kb['rev1']}] status=stale" in text
    assert "status=ok" in text
    assert "kb diff demo-doc" in text  # gợi ý xem thay đổi cho ref stale
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_resolve.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.resolve'`

- [ ] **Step 3: Implement `src/aero_kb/resolve.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from aero_kb import gitio, models
from aero_kb.kbcontext import KBContext, KBRef
from aero_kb.mdutils import count_tokens, slice_section

Status = Literal["ok", "stale", "broken"]


@dataclass
class ResolvedRef:
    ref: KBRef
    status: Status
    citation: str
    content: str
    tokens: int
    reason: str = ""


def _broken(ref: KBRef, reason: str) -> ResolvedRef:
    return ResolvedRef(
        ref=ref, status="broken", citation=str(ref), content="", tokens=0, reason=reason
    )


def _worktree_section(kb_dir: Path, ref: KBRef) -> str | None:
    manifest_path = kb_dir / ref.doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return None
    l2 = kb_dir / ref.doc_id / f"{sec.file}.md"
    if not l2.exists():
        return None
    return slice_section(l2.read_text(encoding="utf-8"), ref.section_id)


def _resolve_one(kb_dir: Path, root: Path, rev: str, ref: KBRef) -> ResolvedRef:
    try:
        manifest_text = gitio.read_at(
            root, rev, kb_dir / ref.doc_id / "_manifest.yaml"
        )
    except gitio.GitError as exc:
        return _broken(ref, str(exc))
    if manifest_text is None:
        return _broken(ref, f"doc '{ref.doc_id}' không tồn tại tại rev {rev}")
    manifest = models.Manifest.model_validate(yaml.safe_load(manifest_text) or {})
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return _broken(
            ref, f"§{ref.section_id} không có trong manifest '{ref.doc_id}' tại rev {rev}"
        )
    l2_text = gitio.read_at(root, rev, kb_dir / ref.doc_id / f"{sec.file}.md")
    if l2_text is None:
        return _broken(ref, f"file L2 '{sec.file}.md' không tồn tại tại rev {rev}")
    pinned = slice_section(l2_text, ref.section_id)
    if pinned is None:
        return _broken(
            ref, f"không slice được §{ref.section_id} trong '{sec.file}.md' tại rev {rev}"
        )

    citation = f"{ref} ({manifest.revision})" if manifest.revision else str(ref)
    now = _worktree_section(kb_dir, ref)
    if now is None:
        status: Status = "stale"
        reason = "section không còn ở worktree (đã xóa hoặc đổi id)"
    elif now.strip() != pinned.strip():
        status = "stale"
        reason = "nội dung L2 đã thay đổi so với bản pin (amendment sau khi BA viết)"
    else:
        status = "ok"
        reason = ""
    return ResolvedRef(
        ref=ref,
        status=status,
        citation=citation,
        content=pinned,
        tokens=count_tokens(pinned),
        reason=reason,
    )


def resolve_refs(kb_dir: Path, ctx: KBContext) -> list[ResolvedRef]:
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    return [_resolve_one(kb_abs, root, ctx.version, ref) for ref in ctx.refs]


def render_resolved(results: list[ResolvedRef], version: str) -> str:
    parts: list[str] = []
    for r in results:
        parts.append(f"--- [{r.citation} @ {version}] status={r.status} ~{r.tokens}tk")
        if r.status == "broken":
            parts.append(f"!! {r.reason}")
        elif r.status == "stale":
            parts.append(
                f"!! {r.reason} — chạy `kb diff {r.ref.doc_id}` để xem thay đổi"
            )
        if r.content:
            parts.append(r.content)
        parts.append("")
    return "\n".join(parts).strip()
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_resolve.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/resolve.py tests/test_resolve.py
git commit -m "feat: resolve — trả section đúng version pin, gắn freshness ok/stale/broken"
```

---

### Task 4: `diff.py` — so sánh KB giữa worktree và git rev

**Files:**
- Create: `src/aero_kb/diff.py`
- Test: `tests/test_diff.py`

**Interfaces:**
- Consumes: `gitio` (Task 1), `models`, `mdutils.slice_section`.
- Produces (Task 7 dùng):
  - `@dataclass SectionChange`: `section_id: str`, `title: str`, `summary_changed: bool = False`, `content_changed: bool = False`
  - `@dataclass DiffReport`: `doc_id: str`, `against: str`, `added: list[SectionChange]`, `removed: list[SectionChange]`, `changed: list[SectionChange]`; property `has_changes: bool`
  - `diff_doc(kb_dir: Path, doc_id: str, against: str = "HEAD") -> DiffReport` — raise `ValueError` nếu doc không có ở rev hoặc worktree; raise `GitError` nếu rev sai/không repo
  - `render_diff(report: DiffReport) -> str`

**Ngữ nghĩa changed (spec §7):** section có ở cả hai bên và (summary L1 đổi HOẶC nội dung raw L3 đổi). So sánh sau `.strip()`. L2 KHÔNG so ở đây (L2 là việc của resolve).

- [ ] **Step 1: Viết test fail** — `tests/test_diff.py`

```python
import pytest

from aero_kb import models
from aero_kb.diff import diff_doc, render_diff


def test_changed_summary_detected(git_kb):
    # fixture: §1.1 đổi summary (L1) giữa rev1 và worktree; L3 giữ nguyên
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    assert [c.section_id for c in report.changed] == ["1.1"]
    assert report.changed[0].summary_changed is True
    assert report.changed[0].content_changed is False
    assert not report.added and not report.removed
    assert report.has_changes


def test_no_changes_against_head(git_kb):
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert not report.has_changes


def test_content_changed_when_raw_edited(git_kb):
    raw = git_kb["kb"] / "demo-doc" / "ch1-records.raw.md"
    raw.write_text(
        raw.read_text(encoding="utf-8").replace(
            "Full raw text about airway records", "Full raw text REVISED airway"
        ),
        encoding="utf-8",
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.changed] == ["1.2"]
    assert report.changed[0].content_changed is True


def test_added_and_removed_sections(git_kb):
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    kept = [s for s in manifest.sections if s.id != "1.2"]  # xóa 1.2
    kept.append(
        models.SectionEntry(id="1.3", title="Waypoint Records", file="ch1-records")
    )
    models.save_yaml_model(
        manifest_path,
        models.Manifest(
            id=manifest.id,
            title=manifest.title,
            revision=manifest.revision,
            sections=kept,
        ),
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.added] == ["1.3"]
    assert [c.section_id for c in report.removed] == ["1.2"]


def test_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="khong-co"):
        diff_doc(git_kb["kb"], "khong-co", against="HEAD")


def test_render_diff_groups(git_kb):
    report = diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"])
    text = render_diff(report)
    assert "~ §1.1" in text
    assert "summary" in text
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_diff.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.diff'`

- [ ] **Step 3: Implement `src/aero_kb/diff.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from aero_kb import gitio, models
from aero_kb.mdutils import slice_section


@dataclass
class SectionChange:
    section_id: str
    title: str
    summary_changed: bool = False
    content_changed: bool = False


@dataclass
class DiffReport:
    doc_id: str
    against: str
    added: list[SectionChange] = field(default_factory=list)
    removed: list[SectionChange] = field(default_factory=list)
    changed: list[SectionChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)


def _raw_section(text: str | None, section_id: str) -> str | None:
    if text is None:
        return None
    return slice_section(text, section_id)


def diff_doc(kb_dir: Path, doc_id: str, against: str = "HEAD") -> DiffReport:
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    doc_dir = kb_abs / doc_id

    new_path = doc_dir / "_manifest.yaml"
    if not new_path.exists():
        raise ValueError(f"doc '{doc_id}' không có trong worktree ({new_path})")
    new = models.load_yaml_model(new_path, models.Manifest)

    old_text = gitio.read_at(root, against, new_path)
    if old_text is None:
        raise ValueError(f"doc '{doc_id}' không tồn tại tại rev '{against}'")
    old = models.Manifest.model_validate(yaml.safe_load(old_text) or {})

    old_by_id = {s.id: s for s in old.sections}
    new_by_id = {s.id: s for s in new.sections}
    report = DiffReport(doc_id=doc_id, against=against)

    report.added = [
        SectionChange(s.id, s.title) for s in new.sections if s.id not in old_by_id
    ]
    report.removed = [
        SectionChange(s.id, s.title) for s in old.sections if s.id not in new_by_id
    ]

    raw_cache_old: dict[str, str | None] = {}
    for sec in new.sections:
        old_sec = old_by_id.get(sec.id)
        if old_sec is None:
            continue
        summary_changed = old_sec.summary.strip() != sec.summary.strip()

        new_raw_path = doc_dir / f"{sec.file}.raw.md"
        new_raw = (
            slice_section(new_raw_path.read_text(encoding="utf-8"), sec.id)
            if new_raw_path.exists()
            else None
        )
        if old_sec.file not in raw_cache_old:
            raw_cache_old[old_sec.file] = gitio.read_at(
                root, against, doc_dir / f"{old_sec.file}.raw.md"
            )
        old_raw = _raw_section(raw_cache_old[old_sec.file], sec.id)
        content_changed = (new_raw or "").strip() != (old_raw or "").strip()

        if summary_changed or content_changed:
            report.changed.append(
                SectionChange(
                    sec.id,
                    sec.title,
                    summary_changed=summary_changed,
                    content_changed=content_changed,
                )
            )
    return report


def render_diff(report: DiffReport) -> str:
    if not report.has_changes:
        return f"{report.doc_id}: không có thay đổi so với {report.against}"
    lines = [f"{report.doc_id} — thay đổi so với {report.against}:"]
    for c in report.added:
        lines.append(f"+ §{c.section_id} {c.title}")
    for c in report.removed:
        lines.append(f"- §{c.section_id} {c.title}")
    for c in report.changed:
        kinds = [k for k, on in (("summary", c.summary_changed), ("content", c.content_changed)) if on]
        lines.append(f"~ §{c.section_id} {c.title} ({', '.join(kinds)})")
    return "\n".join(lines)
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_diff.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/diff.py tests/test_diff.py
git commit -m "feat: diff — so section added/removed/changed giữa worktree và git rev"
```

---

### Task 5: `doctor.py` — sức khỏe KB + kiểm tra kb-context

**Files:**
- Create: `src/aero_kb/doctor.py`
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `models`, `mdutils.slice_section`, `kbcontext.parse/KBContextError` (Task 2), `resolve.resolve_refs/ResolvedRef` (Task 3), `gitio.GitError` (Task 1).
- Produces (Task 7 dùng):
  - `@dataclass Issue`: `level: Literal["error", "warning"]`, `message: str`
  - `check_kb(kb_dir: Path) -> list[Issue]`
  - `check_context(kb_dir: Path, text: str) -> tuple[list[Issue], list[ResolvedRef]]` — không raise; lỗi parse/git thành Issue error. `broken` → error, `stale` → warning. CLI dựa vào list ResolvedRef để tính exit 2.

- [ ] **Step 1: Viết test fail** — `tests/test_doctor.py`

```python
from pathlib import Path

from aero_kb import models
from aero_kb.doctor import check_context, check_kb


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def _warnings(issues):
    return [i.message for i in issues if i.level == "warning"]


def test_clean_kb_no_issues(fixture_kb: Path):
    assert check_kb(fixture_kb) == []


def test_missing_index(tmp_path: Path):
    issues = check_kb(tmp_path)
    assert any("index.yaml" in m for m in _errors(issues))


def test_doc_in_index_without_manifest(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "_manifest.yaml").unlink()
    issues = check_kb(fixture_kb)
    assert any("_manifest.yaml" in m for m in _errors(issues))


def test_manifest_dir_not_in_index(fixture_kb: Path):
    orphan = fixture_kb / "doc-la"
    orphan.mkdir()
    models.save_yaml_model(
        orphan / "_manifest.yaml", models.Manifest(id="doc-la", title="Lạ")
    )
    issues = check_kb(fixture_kb)
    assert any("doc-la" in m for m in _errors(issues))


def test_section_file_missing(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "ch1-records.raw.md").unlink()
    issues = check_kb(fixture_kb)
    assert any("ch1-records.raw.md" in m for m in _errors(issues))


def test_section_not_sliceable(fixture_kb: Path):
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text("## 9.9 Khac\n\nnoi dung khac", encoding="utf-8")
    issues = check_kb(fixture_kb)
    assert any("1.1" in m for m in _errors(issues))


def test_orphan_md_file_warns(fixture_kb: Path):
    (fixture_kb / "demo-doc" / "bo-roi.md").write_text("## x", encoding="utf-8")
    issues = check_kb(fixture_kb)
    assert any("bo-roi.md" in m for m in _warnings(issues))


def test_pending_sections_warn(fixture_kb: Path):
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(manifest_path, manifest)
    issues = check_kb(fixture_kb)
    assert any("pending" in m for m in _warnings(issues))


def test_check_context_stale_is_warning(git_kb):
    block = f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n"
    issues, results = check_context(git_kb["kb"], block)
    assert results[0].status == "stale"
    assert _warnings(issues) and not _errors(issues)


def test_check_context_broken_is_error(git_kb):
    block = f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §9.9\n"
    issues, results = check_context(git_kb["kb"], block)
    assert results[0].status == "broken"
    assert _errors(issues)


def test_check_context_bad_block_is_error(git_kb):
    issues, results = check_context(git_kb["kb"], "không có block")
    assert _errors(issues) and results == []
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.doctor'`

- [ ] **Step 3: Implement `src/aero_kb/doctor.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from aero_kb import gitio, kbcontext, models
from aero_kb.mdutils import slice_section
from aero_kb.resolve import ResolvedRef, resolve_refs


@dataclass
class Issue:
    level: Literal["error", "warning"]
    message: str


def _check_doc(kb_dir: Path, doc_id: str) -> list[Issue]:
    issues: list[Issue] = []
    doc_dir = kb_dir / doc_id
    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)

    pending = 0
    referenced: set[str] = {"_manifest.yaml"}
    for sec in manifest.sections:
        if sec.status == "pending":
            pending += 1
        for suffix, layer in ((".md", "L2"), (".raw.md", "L3")):
            name = f"{sec.file}{suffix}"
            referenced.add(name)
            path = doc_dir / name
            if not path.exists():
                issues.append(
                    Issue("error", f"{doc_id} §{sec.id}: thiếu file {layer} '{name}'")
                )
            elif slice_section(path.read_text(encoding="utf-8"), sec.id) is None:
                issues.append(
                    Issue(
                        "error",
                        f"{doc_id} §{sec.id}: không slice được section trong '{name}'",
                    )
                )
    if pending:
        issues.append(Issue("warning", f"{doc_id}: {pending} section pending"))
    for f in sorted(doc_dir.glob("*.md")):
        if f.name not in referenced:
            issues.append(
                Issue("warning", f"{doc_id}: file mồ côi '{f.name}' không thuộc manifest")
            )
    return issues


def check_kb(kb_dir: Path) -> list[Issue]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return [Issue("error", f"không có index.yaml trong '{kb_dir}'")]
    index = models.load_yaml_model(index_path, models.KBIndex)
    index_ids = {d.id for d in index.docs}

    issues: list[Issue] = []
    for entry in index.docs:
        if not (kb_dir / entry.id / "_manifest.yaml").exists():
            issues.append(
                Issue(
                    "error",
                    f"doc '{entry.id}' có trong index nhưng thiếu _manifest.yaml",
                )
            )
            continue
        issues += _check_doc(kb_dir, entry.id)

    for child in sorted(p for p in kb_dir.iterdir() if p.is_dir()):
        if (child / "_manifest.yaml").exists() and child.name not in index_ids:
            issues.append(
                Issue(
                    "error",
                    f"doc '{child.name}' có manifest nhưng không có trong index.yaml",
                )
            )
    return issues


def check_context(
    kb_dir: Path, text: str
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(kb_dir, ctx)
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

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_doctor.py -v`
Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/doctor.py tests/test_doctor.py
git commit -m "feat: doctor — kiểm tra toàn vẹn KB và staleness của kb-context"
```

---

### Task 6: CLI `kb context new` + `kb resolve`

**Files:**
- Modify: `src/aero_kb/cli.py`
- Test: `tests/test_cli_context.py`

**Interfaces:**
- Consumes: `kbcontext` (Task 2), `resolve` (Task 3), `gitio` (Task 1), `query.get_section`.
- Produces: lệnh `kb context new --refs ... [--tags ...] [--kb-dir ...]` (exit 1 nếu ref không resolve được ở worktree; cảnh báo nếu `.kb/` dirty) và `kb resolve <file|-> [--kb-dir ...]` (exit 0 sạch / 1 có broken / 2 chỉ stale).

- [ ] **Step 1: Viết test fail** — `tests/test_cli_context.py`

```python
from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_context_new_prints_block_with_head_hash(git_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1,demo-doc §1.2",
         "--tags", "demo,airspace", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "kb-context:" in result.output
    assert f"version: {git_kb['rev2']}" in result.output
    assert "- demo-doc §1.1" in result.output
    assert "tags: [demo, airspace]" in result.output


def test_context_new_rejects_unresolvable_ref(git_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §9.9", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
    assert "9.9" in result.output


def test_context_new_warns_when_kb_dirty(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nsua chua commit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "chưa commit" in result.output


def test_resolve_reads_block_from_file(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("ticket") / "tal-1.md"
    ticket.write_text(
        f"# TAL-1\n\nkb-context:\n  version: {git_kb['rev1']}\n  refs:\n"
        "    - demo-doc §1.1\n    - demo-doc §1.2\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 2  # có stale (§1.1), không broken
    assert "status=stale" in result.output
    assert "status=ok" in result.output


def test_resolve_broken_exits_1(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("ticket") / "tal-2.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    assert "status=broken" in result.output


def test_resolve_stdin(git_kb):
    block = f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §1.2\n"
    result = runner.invoke(
        app, ["resolve", "-", "--kb-dir", str(git_kb["kb"])], input=block
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_cli_context.py -v`
Expected: FAIL — exit code 2 kèm "No such command 'context'" / "'resolve'"

- [ ] **Step 3: Thêm vào `src/aero_kb/cli.py`**

Đầu file thêm `import sys`. Sau định nghĩa `app` thêm sub-app; các command mới đặt cuối file:

```python
context_app = typer.Typer(help="Thao tác với block kb-context (citation máy-đọc-được).")
app.add_typer(context_app, name="context")
```

```python
@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Refs phân cách dấu phẩy, vd 'arinc-424 §5.3,arinc-424 §5.3.2'"
    ),
    tags: str = typer.Option("", help="Tags, phân cách bằng dấu phẩy"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Sinh block kb-context pin tại HEAD — dán vào Jira ticket."""
    from aero_kb import gitio, kbcontext
    from aero_kb.query import get_section

    try:
        ref_list = [kbcontext.parse_ref(r) for r in refs.split(",") if r.strip()]
        root = gitio.git_root(kb_dir.resolve())
        version = gitio.head_commit(root)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    bad = [str(r) for r in ref_list
           if get_section(kb_dir, r.doc_id, r.section_id) is None]
    if bad:
        typer.secho(
            f"Ref không resolve được ở worktree: {', '.join(bad)}", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if gitio.is_dirty(root, kb_dir.resolve()):
        typer.secho(
            "[warn] .kb/ có thay đổi chưa commit — hash pin sẽ không chứa thay đổi đó",
            fg=typer.colors.YELLOW,
        )
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    ctx = kbcontext.KBContext(version=version, refs=ref_list, tags=tag_list)
    typer.echo(kbcontext.render(ctx))


@app.command()
def resolve(
    source: str = typer.Argument(
        ..., help="File chứa block kb-context (hoặc '-' đọc từ stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """Resolve block kb-context: trả section đúng version pin + freshness."""
    from aero_kb import gitio, kbcontext
    from aero_kb.resolve import render_resolved, resolve_refs

    text = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    try:
        ctx = kbcontext.parse(text)
        results = resolve_refs(kb_dir, ctx)
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_resolved(results, ctx.version))
    if any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_cli_context.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/cli.py tests/test_cli_context.py
git commit -m "feat: cli — kb context new sinh block pin HEAD, kb resolve với exit 0/1/2"
```

---

### Task 7: CLI `kb diff` + `kb doctor`

**Files:**
- Modify: `src/aero_kb/cli.py`
- Test: `tests/test_cli_doctor_diff.py`

**Interfaces:**
- Consumes: `diff.diff_doc/render_diff` (Task 4), `doctor.check_kb/check_context` (Task 5), `gitio.GitError`.
- Produces: `kb diff <doc-id> [--against HEAD] [--kb-dir]` (exit 0; exit 1 nếu lỗi); `kb doctor [--context <file|->] [--kb-dir]` (exit 0 sạch / 1 error / 2 chỉ stale).

- [ ] **Step 1: Viết test fail** — `tests/test_cli_doctor_diff.py`

```python
from typer.testing import CliRunner

from aero_kb.cli import app

runner = CliRunner()


def test_diff_shows_changed_section(git_kb):
    result = runner.invoke(
        app,
        ["diff", "demo-doc", "--against", git_kb["rev1"], "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output


def test_diff_unknown_doc_exits_1(git_kb):
    result = runner.invoke(
        app, ["diff", "khong-co", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1


def test_doctor_clean_kb(git_kb):
    result = runner.invoke(app, ["doctor", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_doctor_broken_kb_exits_1(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.raw.md").unlink()
    result = runner.invoke(app, ["doctor", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1
    assert "[error]" in result.output


def test_doctor_context_stale_exits_2(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 2
    assert "[warning]" in result.output


def test_doctor_context_broken_exits_1(git_kb, tmp_path_factory):
    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f"kb-context:\n  version: {git_kb['rev2']}\n  refs:\n    - demo-doc §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_cli_doctor_diff.py -v`
Expected: FAIL — "No such command 'diff'" / "'doctor'"

- [ ] **Step 3: Thêm vào `src/aero_kb/cli.py`**

```python
@app.command()
def diff(
    doc_id: str = typer.Argument(..., help="ID tài liệu"),
    against: str = typer.Option("HEAD", help="Git rev để so, vd HEAD, a3f9c21"),
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
) -> None:
    """So section added/removed/changed giữa worktree và một git rev."""
    from aero_kb import gitio
    from aero_kb.diff import diff_doc, render_diff

    try:
        report = diff_doc(kb_dir, doc_id, against=against)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    typer.echo(render_diff(report))


@app.command()
def doctor(
    kb_dir: Path = typer.Option(Path(".kb"), help="Thư mục KB"),
    context: str | None = typer.Option(
        None, "--context", help="File chứa block kb-context (hoặc '-' đọc từ stdin)"
    ),
) -> None:
    """Kiểm tra sức khỏe KB; kèm --context để check staleness của citation."""
    from aero_kb.doctor import check_context, check_kb

    issues = check_kb(kb_dir)
    has_stale = False
    if context is not None:
        text = sys.stdin.read() if context == "-" else Path(context).read_text(
            encoding="utf-8"
        )
        ctx_issues, results = check_context(kb_dir, text)
        issues += ctx_issues
        has_stale = any(r.status == "stale" for r in results)

    for issue in issues:
        color = typer.colors.RED if issue.level == "error" else typer.colors.YELLOW
        typer.secho(f"[{issue.level}] {issue.message}", fg=color)
    if any(i.level == "error" for i in issues):
        raise typer.Exit(1)
    if has_stale:
        raise typer.Exit(2)
    typer.echo("kb doctor: OK")
```

- [ ] **Step 4: Chạy test, xác nhận pass**

Run: `pytest tests/test_cli_doctor_diff.py -v` — Expected: 6 PASS.
Run: `pytest -q` — Expected: toàn bộ pass (regression).

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/cli.py tests/test_cli_doctor_diff.py
git commit -m "feat: cli — kb diff và kb doctor với exit code 0/1/2 cho CI"
```

---

### Task 8: Heading pattern thành config (lưu ý 1)

**Files:**
- Modify: `src/aero_kb/ingest/sectioner.py` (thay `_CHAPTER_RE`/`_APPENDIX_RE` bằng `HeadingConfig`)
- Modify: `src/aero_kb/models.py` (thêm `IngestConfig`, field `Manifest.ingest`)
- Modify: `src/aero_kb/ingest/scaffold.py` (persist config vào manifest)
- Modify: `src/aero_kb/ingest/parser.py` (`bookmark_ids` nhận config)
- Modify: `src/aero_kb/cli.py` (lệnh `ingest` thêm 2 option + resolution)
- Test: `tests/test_heading_config.py`

**Interfaces:**
- Consumes: pattern hiện có trong `sectioner.py` (dòng 34–37).
- Produces:
  - `sectioner.DEFAULT_CHAPTER_PATTERN`, `sectioner.DEFAULT_APPENDIX_PATTERN` (str — giá trị là 2 regex hiện tại, giữ nguyên từng ký tự)
  - `@dataclass sectioner.HeadingConfig(chapter_pattern: str = ..., appendix_pattern: str = ...)` — `__post_init__` compile + validate ≥2 capture group, raise `ValueError` tiếng Việt; expose `chapter_re`, `appendix_re`
  - `sectioner.parse_section_id(text, config: HeadingConfig | None = None)`, `sectioner.build_units(items, config: HeadingConfig | None = None)` — mọi chỗ dùng regex cũ (kể cả check appendix-namespace trong `_build_tree`, hiện ở dòng 91) chuyển qua config
  - `sectioner.resolve_heading_config(chapter_pattern: str, appendix_pattern: str, previous: models.IngestConfig | None) -> HeadingConfig` — ưu tiên: arg tường minh > config cũ trong manifest > default
  - `models.IngestConfig(BaseModel)`: `chapter_pattern: str`, `appendix_pattern: str`; `Manifest.ingest: IngestConfig | None = None`
  - `scaffold.scaffold_doc(..., heading_config: HeadingConfig | None = None)` — luôn ghi config đã dùng vào `manifest.ingest`
  - `parser.bookmark_ids(pdf_path, config: HeadingConfig | None = None)`

- [ ] **Step 1: Viết test fail** — `tests/test_heading_config.py`

```python
import pytest

from aero_kb import models
from aero_kb.ingest import sectioner
from aero_kb.ingest.scaffold import scaffold_doc
from aero_kb.ingest.sectioner import HeadingConfig, SectionUnit


def test_default_config_matches_current_behavior():
    assert sectioner.parse_section_id("Chapter 5 Navigation Data") == (
        "5", "Navigation Data",
    )
    assert sectioner.parse_section_id("APPENDIX 3. Criteria") == ("app3", "Criteria")


def test_custom_chapter_pattern():
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    assert sectioner.parse_section_id("Section 5: Data Fields", config) == (
        "5", "Data Fields",
    )
    # pattern mặc định không còn khớp khi bị override
    assert sectioner.parse_section_id("Chapter 5 Navigation", config) is None


def test_invalid_regex_raises_vietnamese():
    with pytest.raises(ValueError, match="regex"):
        HeadingConfig(chapter_pattern=r"^chuong\s+(\d+")


def test_too_few_groups_raises():
    with pytest.raises(ValueError, match="capture group"):
        HeadingConfig(chapter_pattern=r"^chuong\s+\d+$")


def test_resolve_heading_config_priority():
    prev = models.IngestConfig(
        chapter_pattern=r"^phu luc\s+(\d+)\s+(.*)$",
        appendix_pattern=sectioner.DEFAULT_APPENDIX_PATTERN,
    )
    # arg tường minh thắng manifest
    cfg = sectioner.resolve_heading_config(r"^muc\s+(\d+)\s+(.*)$", "", prev)
    assert cfg.chapter_pattern == r"^muc\s+(\d+)\s+(.*)$"
    # không có arg → lấy từ manifest
    cfg = sectioner.resolve_heading_config("", "", prev)
    assert cfg.chapter_pattern == prev.chapter_pattern
    # không có gì → default
    cfg = sectioner.resolve_heading_config("", "", None)
    assert cfg.chapter_pattern == sectioner.DEFAULT_CHAPTER_PATTERN


def test_scaffold_persists_ingest_config(tmp_path):
    units = [
        SectionUnit(id="5", title="Data", chapter="5", body_md="noi dung", tables=[])
    ]
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    scaffold_doc(
        units, doc_id="doc-x", title="Doc X", tags=[], revision="",
        source_path=None, kb_dir=tmp_path / ".kb", heading_config=config,
    )
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "doc-x" / "_manifest.yaml", models.Manifest
    )
    assert manifest.ingest is not None
    assert manifest.ingest.chapter_pattern == config.chapter_pattern


def test_build_units_accepts_config():
    from aero_kb.ingest.sectioner import DocItem, build_units

    items = [
        DocItem("heading", "Section 1 Records", 1),
        DocItem("text", "body text"),
    ]
    config = HeadingConfig(chapter_pattern=r"^section\s+(\d+)\s*[.:]?\s*(.*)$")
    units = build_units(items, config=config)
    assert units[0].id == "1"
```

- [ ] **Step 2: Chạy test, xác nhận fail**

Run: `pytest tests/test_heading_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'HeadingConfig'`

- [ ] **Step 3: Implement**

`src/aero_kb/models.py` — thêm sau `SectionTokens`:

```python
class IngestConfig(BaseModel):
    chapter_pattern: str
    appendix_pattern: str
```

và trong `Manifest` thêm field cuối: `ingest: IngestConfig | None = None`.

`src/aero_kb/ingest/sectioner.py` — thay dòng 34–37 (`_CHAPTER_RE`, `_APPENDIX_RE`) bằng:

```python
DEFAULT_CHAPTER_PATTERN = r"^chapter\s+(\d+)\s*[.:–—-]?\s*(.*)$"
DEFAULT_APPENDIX_PATTERN = r"^appendix\s+([0-9A-Za-z]+)\s*[.:–—-]?\s*(.*)$"


def _compile_heading(name: str, pattern: str) -> re.Pattern[str]:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"{name}: regex không hợp lệ — {exc}") from exc
    if rx.groups < 2:
        raise ValueError(f"{name}: cần ít nhất 2 capture group (định danh, title)")
    return rx


@dataclass
class HeadingConfig:
    """Quy ước heading của tài liệu. Default là quy ước tiếng Anh phổ biến
    ("Chapter N", "Appendix X") — tài liệu dùng quy ước khác thì override
    lúc ingest; config đã dùng được persist vào _manifest.yaml."""

    chapter_pattern: str = DEFAULT_CHAPTER_PATTERN
    appendix_pattern: str = DEFAULT_APPENDIX_PATTERN

    def __post_init__(self) -> None:
        self.chapter_re = _compile_heading("chapter_pattern", self.chapter_pattern)
        self.appendix_re = _compile_heading("appendix_pattern", self.appendix_pattern)


_DEFAULT_CONFIG = HeadingConfig()


def resolve_heading_config(
    chapter_pattern: str,
    appendix_pattern: str,
    previous: "models.IngestConfig | None",
) -> HeadingConfig:
    """Ưu tiên: arg tường minh > config cũ trong manifest (re-ingest) > default."""
    prev_ch = previous.chapter_pattern if previous else DEFAULT_CHAPTER_PATTERN
    prev_app = previous.appendix_pattern if previous else DEFAULT_APPENDIX_PATTERN
    return HeadingConfig(
        chapter_pattern=chapter_pattern or prev_ch,
        appendix_pattern=appendix_pattern or prev_app,
    )
```

Thêm `from aero_kb import models` vào imports của sectioner. Sửa các chỗ dùng regex cũ:

- `parse_section_id(text: str, config: HeadingConfig | None = None)`: `cfg = config or _DEFAULT_CONFIG`; `cfg.chapter_re.match(text)` / `cfg.appendix_re.match(text)` thay cho `_CHAPTER_RE`/`_APPENDIX_RE`.
- `_build_tree(items, config: HeadingConfig | None = None)`: `cfg = config or _DEFAULT_CONFIG`; gọi `parse_section_id(item.text, cfg)`; điều kiện namespace appendix (dòng 91 cũ) đổi `_CHAPTER_RE.match(...)` → `cfg.chapter_re.match(...)`.
- `build_units(items, config: HeadingConfig | None = None)`: truyền config xuống `_build_tree`.

`src/aero_kb/ingest/scaffold.py` — signature thêm `heading_config: HeadingConfig | None = None` (import `HeadingConfig` từ sectioner); trước `models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)`:

```python
    cfg = heading_config or HeadingConfig()
    manifest.ingest = models.IngestConfig(
        chapter_pattern=cfg.chapter_pattern, appendix_pattern=cfg.appendix_pattern
    )
```

(gán field trước khi save — tạo `Manifest(...)` với `ingest=` trực tiếp cũng được, chọn cách nào thì giữ nhất quán.)

`src/aero_kb/ingest/parser.py` — `bookmark_ids(pdf_path: Path, config=None)`, truyền `config` vào `parse_section_id(title, config)` (thêm type `HeadingConfig | None`).

`src/aero_kb/cli.py` — lệnh `ingest` thêm 2 option và resolution trước khi gọi `build_units`:

```python
    chapter_pattern: str = typer.Option(
        "", help="Regex heading chương (mặc định: 'Chapter N', tự nhớ từ lần ingest trước)"
    ),
    appendix_pattern: str = typer.Option(
        "", help="Regex heading appendix (mặc định: 'Appendix X', tự nhớ từ lần ingest trước)"
    ),
```

```python
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    previous = None
    if manifest_path.exists():
        previous = models.load_yaml_model(manifest_path, models.Manifest).ingest
    try:
        heading_config = sectioner.resolve_heading_config(
            chapter_pattern, appendix_pattern, previous
        )
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

rồi: `units = sectioner.build_units(items, config=heading_config)`, `parser.bookmark_ids(pdf, heading_config)`, `scaffold.scaffold_doc(..., heading_config=heading_config)`.

- [ ] **Step 4: Chạy test, xác nhận pass + regression**

Run: `pytest tests/test_heading_config.py -v` — Expected: 7 PASS.
Run: `pytest -q` — Expected: toàn bộ pass (đặc biệt `test_sectioner.py`, `test_scaffold.py`, `test_parser.py` không đổi hành vi với default config).

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/models.py src/aero_kb/ingest/ src/aero_kb/cli.py tests/test_heading_config.py
git commit -m "refactor: heading pattern thành HeadingConfig — engine hết hardcode quy ước trình bày"
```

---

### Task 9: MCP server + `.mcp.json` + dependencies

**Files:**
- Create: `src/aero_kb/mcp.py`
- Create: `.mcp.json` (root repo)
- Modify: `pyproject.toml`
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `query.search/get_section`, `kbcontext.parse/KBContextError` (Task 2), `resolve.resolve_refs/render_resolved` (Task 3), `gitio.GitError` (Task 1).
- Produces:
  - `@dataclass ServerConfig(kb_dir: Path, hub: str | None = None)`
  - `create_server(config: ServerConfig) -> MCPServer` — đăng ký đúng 3 tool `kb_search`, `kb_get_section`, `kb_resolve`
  - `parse_args(argv: list[str] | None = None) -> ServerConfig`
  - `main(argv=None)` — parse args, log cảnh báo nếu có hub, `create_server(...).run()` (stdio)
  - Entry: `python -m aero_kb.mcp --kb .kb/ [--hub <url>]`

- [ ] **Step 1: Thêm dependencies vào `pyproject.toml`**

`dependencies` thêm `"mcp>=2.0",`; `dev` thành `dev = ["pytest>=8.0", "anyio>=4.0"]`.

Run: `source .venv/bin/activate && pip install -e ".[dev]" && python -c "from mcp.server import MCPServer; print('MCPServer ok')"`
Expected: `MCPServer ok`.
**Contingency:** nếu pip không resolve được `mcp>=2.0` (SDK v2 chưa có trên PyPI của môi trường này), hạ pin xuống `mcp>=1.2` và dùng import `from mcp.server.fastmcp import FastMCP as MCPServer` + test client `mcp.shared.memory.create_connected_server_and_client_session` — ghi rõ vào commit message; mọi chỗ khác của task giữ nguyên.

- [ ] **Step 2: Viết test fail** — `tests/test_mcp.py`

```python
import pytest
from mcp import Client

from aero_kb.mcp import ServerConfig, create_server, parse_args


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _text(result) -> str:
    return result.content[0].text


def test_parse_args_defaults():
    config = parse_args([])
    assert str(config.kb_dir) == ".kb"
    assert config.hub is None


def test_parse_args_hub_kept_but_inactive():
    config = parse_args(["--kb", "x/.kb", "--hub", "git@host:kb-hub.git"])
    assert config.hub == "git@host:kb-hub.git"


@pytest.mark.anyio
async def test_lists_exactly_three_tools(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_get_section", "kb_resolve", "kb_search",
        ]


@pytest.mark.anyio
async def test_kb_search_returns_citation(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "airspace designation"}
        )
        assert "demo-doc §1.1" in _text(result)


@pytest.mark.anyio
async def test_kb_search_respects_budget(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        small = await client.call_tool(
            "kb_search", {"query": "records structure", "budget": 1}
        )
        # budget quá nhỏ → chỉ section đầu tiên được trả (search luôn trả >= 1)
        assert _text(small).count("--- [") == 1
        big = await client.call_tool(
            "kb_search", {"query": "records structure", "budget": 5000}
        )
        assert _text(big).count("--- [") == 2


@pytest.mark.anyio
async def test_kb_get_section_l3(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "demo-doc", "section": "1.1", "level": "l3"}
        )
        assert "Full raw text about airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_unknown_doc_suggests(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "demodoc", "section": "1.1"}
        )
        assert "demo-doc" in _text(result)  # gợi ý doc hiện có


@pytest.mark.anyio
async def test_kb_resolve_reports_stale(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    block = f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n"
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": block})
        text = _text(result)
        assert "status=stale" in text
        assert "designation and type fields" in text  # nội dung tại bản pin


@pytest.mark.anyio
async def test_kb_resolve_bad_block_returns_error_text(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": "khong co block"})
        assert "kb-context" in _text(result)
```

- [ ] **Step 3: Chạy test, xác nhận fail**

Run: `pytest tests/test_mcp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aero_kb.mcp'`

- [ ] **Step 4: Implement `src/aero_kb/mcp.py`**

Lưu ý stdio: KHÔNG `print()` trong module này — stdout thuộc về protocol; dùng `logging` (ra stderr).

```python
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from mcp.server import MCPServer

from aero_kb import gitio, kbcontext, models
from aero_kb.query import get_section, search
from aero_kb.resolve import render_resolved, resolve_refs

logger = logging.getLogger("aero_kb.mcp")


@dataclass
class ServerConfig:
    kb_dir: Path
    hub: str | None = None  # Phase 3 — đọc sẵn, chưa kích hoạt


def _known_docs(kb_dir: Path) -> str:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return ""
    index = models.load_yaml_model(index_path, models.KBIndex)
    return ", ".join(d.id for d in index.docs)


def create_server(config: ServerConfig) -> MCPServer:
    mcp = MCPServer("aero-kb")

    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Tìm section theo tag match + BM25; trả nội dung L2 trong token budget, kèm citation."""
        results = search(config.kb_dir, query, tags=tags, budget=budget)
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
        result = get_section(config.kb_dir, doc, section, level=level)
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
            results = resolve_refs(config.kb_dir, ctx)
        except gitio.GitError as exc:
            return f"git lỗi: {exc}"
        return render_resolved(results, ctx.version)

    return mcp


def parse_args(argv: list[str] | None = None) -> ServerConfig:
    ap = argparse.ArgumentParser(
        prog="python -m aero_kb.mcp", description="AERO-KB MCP server (stdio)"
    )
    ap.add_argument("--kb", type=Path, default=Path(".kb"), help="Thư mục KB")
    ap.add_argument(
        "--hub", default=None, help="URL kb-hub (Phase 3 — nhận nhưng chưa kích hoạt)"
    )
    args = ap.parse_args(argv)
    return ServerConfig(kb_dir=args.kb, hub=args.hub)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    config = parse_args(argv)
    if config.hub:
        logger.warning(
            "hub '%s' được cấu hình nhưng chưa kích hoạt trước Phase 3", config.hub
        )
    create_server(config).run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Tạo `.mcp.json` tại root repo**

```json
{
  "mcpServers": {
    "aero-kb": {
      "command": "python",
      "args": ["-m", "aero_kb.mcp", "--kb", ".kb/"]
    }
  }
}
```

- [ ] **Step 6: Chạy test, xác nhận pass + smoke stdio**

Run: `pytest tests/test_mcp.py -v` — Expected: 9 PASS.
Smoke: `python -m aero_kb.mcp --help` — Expected: usage in ra, có `--kb` và `--hub`.

- [ ] **Step 7: Commit**

```bash
git add src/aero_kb/mcp.py tests/test_mcp.py .mcp.json pyproject.toml
git commit -m "feat: MCP server stdio — kb_search/kb_get_section/kb_resolve, --hub optional chờ Phase 3"
```

---

### Task 10: E2E nghiệm thu + cập nhật README

**Files:**
- Test: `tests/test_phase2_e2e.py`
- Modify: `README.md` (thêm mục Phase 2: 3 MCP tool, 4 lệnh CLI mới, flow BA→Dev)

**Interfaces:**
- Consumes: mọi thứ từ Task 1–9. Không produce gì mới.

Kịch bản = tiêu chí hoàn thành 1 + 2 của spec: BA pin tại rev1 → amendment (commit rev2) → Dev resolve ra stale, diff chỉ đúng section, doctor exit 2.

- [ ] **Step 1: Viết test** — `tests/test_phase2_e2e.py`

```python
import pytest
from mcp import Client
from typer.testing import CliRunner

from aero_kb import models
from aero_kb.cli import app
from aero_kb.mcp import ServerConfig, create_server

runner = CliRunner()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_full_loop_ba_to_dev_with_amendment(fixture_kb, run_git):
    root = fixture_kb.parent
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kb v1")

    # 1. BA: sinh block kb-context (pin tại rev1) — dán vào Jira
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1", "--tags", "demo",
         "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 0
    ticket = f"# TAL-1 Airspace popup\n\nAC: hiển thị field theo [demo-doc §1.1]\n\n{result.output}"

    # 2. Amendment sau khi BA viết: sửa L2 + summary §1.1, commit rev2
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airspace record structure with designation and type fields.",
            "airspace record structure with NEW multiple code field.",
        ),
        encoding="utf-8",
    )
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Airspace records: designation, type, multiple code."
    models.save_yaml_model(manifest_path, manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "amendment 1.1")

    # 3. Dev: resolve qua MCP → nhận đúng nội dung BA đã thấy + cảnh báo stale
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with Client(server, raise_exceptions=True) as client:
        resolved = await client.call_tool("kb_resolve", {"kb_context": ticket})
        text = resolved.content[0].text
    assert "status=stale" in text
    assert "designation and type fields" in text  # bản pin, không phải bản mới

    # 4. kb diff chỉ ra đúng section thay đổi để SME/BA review
    rev1 = run_git(root, "rev-list", "--max-parents=0", "--abbrev-commit", "HEAD")
    result = runner.invoke(
        app, ["diff", "demo-doc", "--against", rev1, "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output
    assert "§1.2" not in result.output

    # 5. kb doctor --context: CI phân biệt được "cần BA xác nhận lại" (exit 2)
    ticket_file = root / "ticket.md"
    ticket_file.write_text(ticket, encoding="utf-8")
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket_file), "--kb-dir", str(fixture_kb)],
    )
    assert result.exit_code == 2
```

- [ ] **Step 2: Chạy E2E + toàn bộ suite**

Run: `pytest tests/test_phase2_e2e.py -v` — Expected: 1 PASS (mọi mảnh đã có từ Task 1–9; nếu fail, đây là bug tích hợp — sửa module liên quan, không sửa test).
Run: `pytest -q` — Expected: toàn bộ pass.

- [ ] **Step 3: Cập nhật `README.md`**

Thêm mục "Phase 2 — Tích hợp workflow" sau phần mô tả CLI hiện có, nội dung: bảng 3 MCP tool (`kb_search`, `kb_get_section`, `kb_resolve`) + 4 lệnh CLI mới (`kb context new`, `kb resolve`, `kb diff`, `kb doctor` với exit 0/1/2) + đoạn 5 dòng mô tả flow BA → Jira → Dev (BA `kb context new` → dán block vào ticket → Dev `kb_resolve` → nếu stale thì `kb diff` + trao đổi BA) + ghi chú `.mcp.json` có sẵn trong repo và `--hub` để dành Phase 3.

- [ ] **Step 4: Commit**

```bash
git add tests/test_phase2_e2e.py README.md
git commit -m "test: E2E vòng BA→Jira→Dev với amendment + docs Phase 2 trong README"
```

---

## Self-Review (đã chạy)

1. **Spec coverage:** §4 MCP server → Task 9; §5 kb-context → Task 2 + 6; §6 resolve/pin → Task 3; §7 diff → Task 4; §8 doctor → Task 5 + 7; §9 heading config → Task 8; §10 error handling → nằm trong từng module (broken-per-ref Task 3, GitError Task 1, MCP không raise Task 9, exit codes Task 6/7); §11 testing → test từng task + Task 10 E2E; §12 ràng buộc → Global Constraints. Tiêu chí nghiệm thu 1–2 → Task 10, 3 → Task 9 Step 5, 4 → Task 9 budget test.
2. **Placeholder:** không còn TBD/TODO; mọi bước code đều có code đầy đủ.
3. **Type consistency:** `ResolvedRef`/`resolve_refs`/`render_resolved` dùng thống nhất ở Task 3/5/6/9/10; `HeadingConfig`/`resolve_heading_config` ở Task 8; `ServerConfig`/`create_server`/`parse_args` ở Task 9/10; fixture `git_kb` trả dict keys `root/kb/rev1/rev2` dùng thống nhất ở Task 1/3/4/5/6/7/9.
