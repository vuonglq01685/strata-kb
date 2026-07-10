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
