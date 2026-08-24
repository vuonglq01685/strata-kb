from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import yaml
from pydantic import ValidationError

from center_kb import gitio, models
from center_kb.kbcontext import KBContext, KBRef
from center_kb.mdutils import count_tokens, slice_section

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

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
        # Worktree manifest is broken → treat the section as unreadable in the worktree
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
            ref, f"doc '{ref.doc_id}' does not exist at rev {rev}", pinned_rev=rev
        )
    try:
        manifest = models.Manifest.model_validate(yaml.safe_load(manifest_text) or {})
    except (yaml.YAMLError, ValidationError) as exc:
        return _broken(
            ref,
            f"manifest '{ref.doc_id}' is broken or has an invalid schema at rev {rev}: {exc}",
            pinned_rev=rev,
        )
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return _broken(
            ref,
            f"§{ref.section_id} is not in manifest '{ref.doc_id}' at rev {rev}",
            pinned_rev=rev,
        )
    l2_text = gitio.read_at(root, rev, kb_dir / ref.doc_id / f"{sec.file}.md")
    if l2_text is None:
        return _broken(
            ref, f"L2 file '{sec.file}.md' does not exist at rev {rev}", pinned_rev=rev
        )
    pinned = slice_section(l2_text, ref.section_id)
    if pinned is None:
        return _broken(
            ref,
            f"could not slice §{ref.section_id} in '{sec.file}.md' at rev {rev}",
            pinned_rev=rev,
        )

    citation = f"{ref} ({manifest.revision})" if manifest.revision else str(ref)
    now = _worktree_section(kb_dir, ref)
    if now is None:
        status: Status = "stale"
        reason = "section unreadable in worktree (deleted, id changed, or manifest broken)"
    elif now.strip() != pinned.strip():
        status = "stale"
        reason = "L2 content has changed since the pinned version (amendment after the BA wrote it)"
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


def render_resolved(
    results: list[ResolvedRef], include_content: bool = True
) -> str:
    parts: list[str] = []
    for r in results:
        rev = r.pinned_rev or "?"
        parts.append(f"--- [{r.citation} @ {rev}] status={r.status} ~{r.tokens}tk")
        if r.status == "broken":
            parts.append(f"!! {r.reason}")
        elif r.status == "stale":
            parts.append(
                f"!! {r.reason} — run `kb diff {r.ref.doc_id} --against {rev}` "
                "to see the changes"
            )
        if include_content and r.content:
            parts.append(r.content)
        parts.append("")
    return "\n".join(parts).strip()
