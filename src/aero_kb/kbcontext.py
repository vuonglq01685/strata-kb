from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field


class KBContextError(ValueError):
    """Block kb-context thiếu hoặc sai format."""


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
            f"ref '{text}' sai format — cần '<doc-id> §<section-id>', vd 'arinc-424 §5.3'"
        )
    return KBRef(
        doc_id=m.group("doc"), section_id=m.group("sec"), repo_id=m.group("repo")
    )


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
    hub_version_raw = payload.get("hub_version")
    hub_version = str(hub_version_raw).strip() if hub_version_raw else None
    raw_refs = payload.get("refs") or []
    if not raw_refs:
        raise KBContextError("kb-context thiếu 'refs' — phải cite ít nhất 1 section")
    if not isinstance(raw_refs, list):
        raise KBContextError(
            "'refs' phải là danh sách YAML (mỗi ref một dòng '- ...')"
        )
    refs = [parse_ref(str(r)) for r in raw_refs]
    raw_tags = payload.get("tags") or []
    if not isinstance(raw_tags, list):
        raise KBContextError(
            "'tags' phải là danh sách YAML (mỗi tag một dòng '- ...' hoặc dạng [a, b])"
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
