from __future__ import annotations

import re
from typing import TYPE_CHECKING

import yaml
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from center_kb.hub import HubHandle


class KBContextError(ValueError):
    """kb-context block is missing or malformed."""


class KBRefNotFoundError(KBContextError):
    """A ref does not resolve to any known section in the local KB or hub."""


class KBRef(BaseModel):
    doc_id: str
    section_id: str
    repo_id: str | None = None

    def __str__(self) -> str:
        prefix = f"{self.repo_id}:" if self.repo_id else ""
        return f"{prefix}{self.doc_id} §{self.section_id}"


class KBContext(BaseModel):
    version: str
    hub_version: str | None = None
    refs: list[KBRef]
    tags: list[str] = Field(default_factory=list)


_REF_RE = re.compile(
    r"^(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s+§?(?P<sec>\S+)$"
)
_KEY_RE = re.compile(r"^(?P<indent>\s*)kb-context:\s*$")


def parse_ref(text: str) -> KBRef:
    m = _REF_RE.match(" ".join(text.split()))
    if not m:
        raise KBContextError(
            f"ref '{text}' has the wrong format — expected '<doc-id> §<section-id>', e.g. 'arinc-424 §5.3'"
        )
    return KBRef(
        doc_id=m.group("doc"), section_id=m.group("sec"), repo_id=m.group("repo")
    )


def _extract_block(text: str) -> str:
    """Extract the first kb-context block by indent — tolerates a block embedded in a ticket."""
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
    raise KBContextError("no 'kb-context:' block found in the text")


def parse(text: str) -> KBContext:
    block = _extract_block(text)
    try:
        data = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise KBContextError(f"kb-context block is not valid YAML: {exc}") from exc
    payload = (data or {}).get("kb-context")
    if not isinstance(payload, dict):
        raise KBContextError("kb-context block is empty or malformed")
    version = str(payload.get("version") or "").strip()
    if not version:
        raise KBContextError("kb-context is missing 'version' (commit hash when the BA wrote it)")
    hub_version_raw = payload.get("hub_version")
    hub_version = str(hub_version_raw).strip() if hub_version_raw else None
    raw_refs = payload.get("refs") or []
    if not raw_refs:
        raise KBContextError("kb-context is missing 'refs' — must cite at least 1 section")
    if not isinstance(raw_refs, list):
        raise KBContextError(
            "'refs' must be a YAML list (one ref per line '- ...')"
        )
    refs = [parse_ref(str(r)) for r in raw_refs]
    raw_tags = payload.get("tags") or []
    if not isinstance(raw_tags, list):
        raise KBContextError(
            "'tags' must be a YAML list (one tag per line '- ...' or [a, b] form)"
        )
    tags = [str(t) for t in raw_tags]
    return KBContext(version=version, hub_version=hub_version, refs=refs, tags=tags)


def render(ctx: KBContext) -> str:
    lines = ["kb-context:", f'  version: "{ctx.version}"']
    if ctx.hub_version:
        lines.append(f'  hub_version: "{ctx.hub_version}"')
    lines.append("  refs:")
    lines += [f"    - {ref}" for ref in ctx.refs]
    if ctx.tags:
        lines.append(f"  tags: [{', '.join(ctx.tags)}]")
    return "\n".join(lines)


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
