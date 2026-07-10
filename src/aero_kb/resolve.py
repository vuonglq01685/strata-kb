from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import ValidationError

from aero_kb import gitio, models
from aero_kb.kbcontext import KBContext, KBRef
from aero_kb.mdutils import count_tokens, slice_section

if TYPE_CHECKING:
    from aero_kb.hub import HubHandle

Status = Literal["ok", "stale", "broken"]


@dataclass
class ResolvedRef:
    ref: KBRef
    status: Status
    citation: str
    content: str
    tokens: int
    reason: str = ""
    pinned_rev: str = ""


def _broken(ref: KBRef, reason: str, pinned_rev: str = "") -> ResolvedRef:
    return ResolvedRef(
        ref=ref, status="broken", citation=str(ref), content="", tokens=0,
        reason=reason, pinned_rev=pinned_rev,
    )


def _worktree_section(kb_dir: Path, ref: KBRef) -> str | None:
    manifest_path = kb_dir / ref.doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, ValidationError):
        # Manifest worktree hỏng → coi như section không đọc được ở worktree
        return None
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
        return _broken(ref, str(exc), pinned_rev=rev)
    if manifest_text is None:
        return _broken(
            ref, f"doc '{ref.doc_id}' không tồn tại tại rev {rev}", pinned_rev=rev
        )
    try:
        manifest = models.Manifest.model_validate(yaml.safe_load(manifest_text) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        return _broken(
            ref,
            f"manifest '{ref.doc_id}' hỏng hoặc sai schema tại rev {rev}: {exc}",
            pinned_rev=rev,
        )
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return _broken(
            ref,
            f"§{ref.section_id} không có trong manifest '{ref.doc_id}' tại rev {rev}",
            pinned_rev=rev,
        )
    l2_text = gitio.read_at(root, rev, kb_dir / ref.doc_id / f"{sec.file}.md")
    if l2_text is None:
        return _broken(
            ref, f"file L2 '{sec.file}.md' không tồn tại tại rev {rev}", pinned_rev=rev
        )
    pinned = slice_section(l2_text, ref.section_id)
    if pinned is None:
        return _broken(
            ref,
            f"không slice được §{ref.section_id} trong '{sec.file}.md' tại rev {rev}",
            pinned_rev=rev,
        )

    citation = f"{ref} ({manifest.revision})" if manifest.revision else str(ref)
    now = _worktree_section(kb_dir, ref)
    if now is None:
        status: Status = "stale"
        reason = "section không đọc được ở worktree (đã xóa, đổi id, hoặc manifest hỏng)"
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
        pinned_rev=rev,
    )


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
