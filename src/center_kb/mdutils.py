from __future__ import annotations

import re
import unicodedata

import tiktoken

_ENCODER = None

_HEADING_RE = re.compile(r"^## (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
_SEP_ROW_RE = re.compile(r"^\|[\s:|-]+\|$")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def slugify_id(text: str) -> str:
    """Unicode-aware slug for section ids: keep letters/digits of every
    script (slugify() drops non-ASCII entirely — CJK/Cyrillic titles would
    vanish). File names keep using slugify(); this is for ids only."""
    text = unicodedata.normalize("NFKC", text)
    slug = re.sub(r"[\W_]+", "-", text).strip("-").lower()
    return slug[:40].rstrip("-")


def count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


def slice_section(md: str, section_id: str) -> str | None:
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


_SUBHEADING_RE = re.compile(r"^### (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")


def slice_subsection(md: str, section_id: str) -> str | None:
    """Slice a folded child ('### <id> <title>' inside a unit body) — ends at
    the next '###'/'##' heading. slice_section() only addresses '## ' units;
    folded children need this."""
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _SUBHEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(("## ", "### ")):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


def extract_tables(md: str) -> list[str]:
    tables: list[str] = []
    current: list[str] = []
    for line in md.splitlines() + [""]:
        if line.lstrip().startswith("|"):
            current.append(line.strip())
        else:
            if len(current) >= 2:
                tables.append("\n".join(current))
            current = []
    return tables


_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(assets/[0-9a-f]{64}\.(?:png|webp)\)")


def extract_image_descs(md: str) -> list[str]:
    """Alt-texts of standalone image refs, in order, deduped, blanks dropped.

    Table rows are skipped: table icons already reach L2 inside the copied
    table, byte-identical — they must not also become 'Figure:' lines.
    """
    descs: list[str] = []
    for line in md.splitlines():
        if line.lstrip().startswith("|"):
            continue
        for m in _IMAGE_MD_RE.finditer(line):
            alt = m.group(1).strip()
            if alt and alt not in descs:
                descs.append(alt)
    return descs


def normalize_table(table_md: str) -> str:
    rows: list[str] = []
    for line in table_md.splitlines():
        line = line.strip()
        if not line or _SEP_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append("|".join(" ".join(c.split()) for c in cells))
    return "\n".join(rows)
