# src/center_kb/web/mdrender.py
"""Minimal markdown→HTML for the exact subset used in L2/L3 files.

Supported: #..###### headings, blank-line paragraphs, GitHub pipe tables.
Table cells are escaped but never reworded/reflowed — the project's
inviolable rule is that tables render character-for-character.
"""
from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_separator(row: str) -> bool:
    return "-" in row and bool(_SEPARATOR_RE.match(row))


def _render_table(rows: list[str]) -> str:
    has_header = len(rows) > 1 and _is_separator(rows[1])
    out = ["<table>"]
    for i, row in enumerate(rows):
        if has_header and i == 1:
            continue
        tag = "th" if (has_header and i == 0) else "td"
        cells = "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in _cells(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "".join(out)


def render(md: str) -> str:
    blocks: list[str] = []
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{html.escape(' '.join(para))}</p>")
            para.clear()

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("|"):
            flush_para()
            table: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append(_render_table(table))
            continue
        m = _HEADING_RE.match(line)
        if m:
            flush_para()
            level = len(m.group(1))
            blocks.append(f"<h{level}>{html.escape(m.group(2).strip())}</h{level}>")
        elif not line.strip():
            flush_para()
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    return "\n".join(blocks)
