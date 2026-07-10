from __future__ import annotations

import re

import tiktoken

_ENCODER = None

_HEADING_RE = re.compile(r"^## (?P<sid>\S+)[ \t]+(?P<title>.+?)\s*$")
_SEP_ROW_RE = re.compile(r"^\|[\s:|-]+\|$")


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


def normalize_table(table_md: str) -> str:
    rows: list[str] = []
    for line in table_md.splitlines():
        line = line.strip()
        if not line or _SEP_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append("|".join(" ".join(c.split()) for c in cells))
    return "\n".join(rows)
