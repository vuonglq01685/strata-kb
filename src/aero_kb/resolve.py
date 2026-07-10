from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ValidationError

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
        return _broken(ref, str(exc))
    if manifest_text is None:
        return _broken(ref, f"doc '{ref.doc_id}' không tồn tại tại rev {rev}")
    try:
        manifest = models.Manifest.model_validate(yaml.safe_load(manifest_text) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        return _broken(
            ref, f"manifest '{ref.doc_id}' hỏng hoặc sai schema tại rev {rev}: {exc}"
        )
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
                f"!! {r.reason} — chạy `kb diff {r.ref.doc_id} --against {version}` "
                "để xem thay đổi"
            )
        if r.content:
            parts.append(r.content)
        parts.append("")
    return "\n".join(parts).strip()
