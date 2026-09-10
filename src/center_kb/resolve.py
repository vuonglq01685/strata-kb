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


MISSING_DOC = "missing-doc"
MISSING_SECTION = "missing-section"
BAD_MANIFEST = "bad-manifest"


def _worktree_section(kb_dir: Path, ref: KBRef) -> tuple[str | None, str]:
    """(content, problem). `problem` is '' when the content was read.

    Reviewer C F-C6: this used to return None for all three failures, so
    `_resolve_one` collapsed "the cited standard section no longer exists" into
    the same `stale` bucket as "someone reworded a sentence"."""
    manifest_path = kb_dir / ref.doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None, MISSING_DOC
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, ValidationError):
        return None, BAD_MANIFEST
    sec = next((s for s in manifest.sections if s.id == ref.section_id), None)
    if sec is None:
        return None, MISSING_SECTION
    l2 = kb_dir / ref.doc_id / f"{sec.file}.md"
    if not l2.exists():
        return None, MISSING_SECTION
    body = slice_section(l2.read_text(encoding="utf-8"), ref.section_id)
    if body is None:
        return None, MISSING_SECTION
    return body, ""


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
    now, problem = _worktree_section(kb_dir, ref)
    reasons = {
        MISSING_DOC: (
            f"the cited document '{ref.doc_id}' no longer exists in the "
            "federation — confirm the replacement with the BA, then re-pin "
            "with kb_context_new"
        ),
        MISSING_SECTION: (
            f"the cited section §{ref.section_id} no longer exists in "
            f"'{ref.doc_id}' at the current revision (deleted or renumbered) — "
            "confirm the replacement with the BA, then re-pin with kb_context_new"
        ),
        BAD_MANIFEST: (
            f"manifest for '{ref.doc_id}' is unreadable in the worktree"
        ),
    }
    if problem:
        # broken, not stale: CI must be able to BLOCK on a citation whose target
        # is gone, and must not treat it like an amendment (F-C6). The pinned
        # bytes still resolve, so they travel with the failure.
        return ResolvedRef(
            ref=ref, status="broken", citation=citation, content=pinned,
            tokens=count_tokens(pinned), reason=reasons[problem], pinned_rev=rev,
        )
    if now.strip() != pinned.strip():
        status: Status = "stale"
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

    if ctx.hub_version and ctx.hub_version != ctx.version:
        # F-C6 nit: `hub_version` was parsed and never read, so a legacy
        # two-version block whose `version` happened to be a real hub commit
        # resolved silently as ok — pinning something nobody chose.
        reason = (
            f"kb-context carries both version {ctx.version} and hub_version "
            f"{ctx.hub_version} — a legacy two-version block; re-pin with "
            "kb_context_new"
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
