from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from aero_kb import gitio, kbcontext, models
from aero_kb.mdutils import slice_section
from aero_kb.resolve import ResolvedRef, resolve_refs

if TYPE_CHECKING:
    from aero_kb.hub import HubHandle


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
    kb_dir: Path, text: str, hub: "HubHandle | None" = None
) -> tuple[list[Issue], list[ResolvedRef]]:
    try:
        ctx = kbcontext.parse(text)
    except kbcontext.KBContextError as exc:
        return [Issue("error", str(exc))], []
    try:
        results = resolve_refs(kb_dir, ctx, hub=hub)
    except gitio.GitError as exc:
        return [Issue("error", str(exc))], []

    issues: list[Issue] = []
    for r in results:
        if r.status == "broken":
            issues.append(Issue("error", f"{r.ref}: {r.reason}"))
        elif r.status == "stale":
            issues.append(Issue("warning", f"{r.ref}: {r.reason}"))
    return issues, results


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
