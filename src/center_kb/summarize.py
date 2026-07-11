from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from center_kb import models
from center_kb.mdutils import slice_section

SECTION_PROMPT = """You are filling in summaries for a knowledge-base section.

Section {section_id} — {title}

<source>
{l3_body}
</source>

Write two summaries of the source text, following ALL rules:
- Write in English.
- l2_summary: condense the prose to ~20-30% of the original length, keep the \
logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...), \
numeric values, units, cross-references (§x.y). Never paraphrase technical terms.
- Do not invent anything that is not in the source. When unsure, keep the \
original sentence.
- Do not summarize, create, or delete tables (tables are handled separately).
- l1_summary: one sentence, max 25 words, stating what the section covers and \
what kind of data it contains.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"l2_summary": "...", "l1_summary": "..."}}"""

DOC_PROMPT = """These are the one-line summaries of every section in the \
document "{title}":

{l1_lines}

Write ONE English sentence (max 30 words) summarizing what the whole document \
covers. Reply with ONLY a JSON object:
{{"summary": "..."}}"""


@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str


def collect_pending(kb_dir: Path, doc_id: str | None = None) -> list[PendingSection]:
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    out: list[PendingSection] = []
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        raw_cache: dict[str, str] = {}
        for sec in manifest.sections:
            if sec.status != "pending":
                continue
            if sec.file not in raw_cache:
                raw_path = kb_dir / entry.id / f"{sec.file}.raw.md"
                raw_cache[sec.file] = (
                    raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
                )
            body = slice_section(raw_cache[sec.file], sec.id) or ""
            out.append(PendingSection(entry.id, sec.id, sec.title, sec.file, body))
    return out


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id, title=section.title, l3_body=section.l3_body
    )


def build_doc_prompt(title: str, l1_summaries: list[str]) -> str:
    return DOC_PROMPT.format(title=title, l1_lines="\n".join(f"- {s}" for s in l1_summaries))


def parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]:
    """Extract the first JSON object; every required key must be a non-empty str."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    out: dict[str, str] = {}
    for key in required:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing or empty key: {key}")
        out[key] = value.strip()
    return out


def replace_marker(l2_text: str, section_id: str, summary: str) -> str:
    marker = f"<!-- TODO:summarize {section_id} -->"
    if marker not in l2_text:
        raise ValueError(f"marker not found: {marker}")
    return l2_text.replace(marker, summary, 1)
