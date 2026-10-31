# src/strata_kb/web/mdrender.py
"""Minimal markdown→HTML for the exact subset used in L2/L3 files.

Supported: #..###### headings, blank-line paragraphs, GitHub pipe tables,
sha-named asset images (as standalone blocks or table cells), fenced code
blocks (verbatim, never highlighted), `- `/`* ` bullet lists, and inline
`**strong**`, `*em*`/`_em_` and `` `code` `` in paragraphs and headings. Table
cells are escaped but never reworded/reflowed or inline-parsed — the project's inviolable
rule is that tables render character-for-character. Optional keyword
highlighting wraps matched whole words in <mark> without altering any
other character.
"""

from __future__ import annotations

import html
import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_SEPARATOR_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_IMG_LINE_RE = re.compile(r"^!\[([^\]]*)\]\(assets/([0-9a-f]{64}\.(?:png|webp))\)$")
_FENCE_RE = re.compile(r"^```[\w-]*\s*$")
_LIST_RE = re.compile(r"^[-*] (.*)$")
# Inline rules, applied in order; a delimiter hugs non-space text and has no
# word character (or another delimiter) on its outer side, so `2*3*4`,
# `snake_case` and `a * b` stay literal.
_INLINE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"`([^`\n]+)`"), "code"),
    (re.compile(r"(?<![\w*])\*\*(\S|\S.*?\S)\*\*(?![\w*])"), "strong"),
    (
        re.compile(
            r"(?<![\w*])\*(\S|\S.*?\S)\*(?![\w*])|(?<![\w_])_(\S|\S.*?\S)_(?![\w_])"
        ),
        "em",
    ),
)


def _img_tag(m: re.Match[str]) -> str:
    alt, name = m.group(1), m.group(2)
    return f'<img src="/assets/{name}" alt="{html.escape(alt, quote=True)}" loading="lazy">'


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _is_separator(row: str) -> bool:
    return "-" in row and bool(_SEPARATOR_RE.match(row))


def _highlight(text: str, terms: set[str]) -> str:
    if not terms:
        return html.escape(text)
    out: list[str] = []
    last = 0
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        if word.lower() in terms:
            out.append(html.escape(text[last : m.start()]))
            out.append(f"<mark>{html.escape(word)}</mark>")
            last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def _inline(text: str, terms: set[str], rule: int = 0) -> str:
    """Escape `text`, add inline tags, highlight `terms` outside code spans."""
    if rule == len(_INLINE_RULES):
        return _highlight(text, terms)
    regex, tag = _INLINE_RULES[rule]
    out: list[str] = []
    last = 0
    for m in regex.finditer(text):
        out.append(_inline(text[last : m.start()], terms, rule + 1))
        inner = next(g for g in m.groups() if g is not None)
        body = html.escape(inner) if tag == "code" else _inline(inner, terms, rule + 1)
        out.append(f"<{tag}>{body}</{tag}>")
        last = m.end()
    out.append(_inline(text[last:], terms, rule + 1))
    return "".join(out)


def _render_table(rows: list[str], terms: set[str]) -> str:
    has_header = len(rows) > 1 and _is_separator(rows[1])
    out = ["<table>"]
    for i, row in enumerate(rows):
        if has_header and i == 1:
            continue
        tag = "th" if (has_header and i == 0) else "td"
        cells = "".join(f"<{tag}>{_cell_html(c, terms)}</{tag}>" for c in _cells(row))
        out.append(f"<tr>{cells}</tr>")
    out.append("</table>")
    return "".join(out)


def _cell_html(cell: str, terms: set[str]) -> str:
    m = _IMG_LINE_RE.match(cell)
    if m:
        return _img_tag(m)
    return _highlight(cell, terms)


def render(md: str, terms: set[str] | None = None) -> str:
    terms = terms or set()
    blocks: list[str] = []
    para: list[str] = []
    bullets: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{_inline(' '.join(para), terms)}</p>")
            para.clear()

    def flush_list() -> None:
        if bullets:
            blocks.append("<ul>" + "".join(bullets) + "</ul>")
            bullets.clear()

    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            flush_para()
            flush_list()
            i += 1
            code: list[str] = []
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence, or one past the end
            body = "\n".join(code)
            blocks.append(f"<pre><code>{html.escape(body)}</code></pre>")
            continue
        if line.lstrip().startswith("|"):
            flush_para()
            flush_list()
            table: list[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                table.append(lines[i])
                i += 1
            blocks.append(_render_table(table, terms))
            continue
        m_img = _IMG_LINE_RE.match(line.strip())
        if m_img:
            flush_para()
            flush_list()
            blocks.append(_img_tag(m_img))
            i += 1
            continue
        m = _HEADING_RE.match(line)
        m_li = _LIST_RE.match(line)
        if m:
            flush_para()
            flush_list()
            level = len(m.group(1))
            blocks.append(f"<h{level}>{_inline(m.group(2).strip(), terms)}</h{level}>")
        elif m_li:
            flush_para()
            bullets.append(f"<li>{_highlight(m_li.group(1).strip(), terms)}</li>")
        elif not line.strip():
            flush_para()  # a blank line does not end a list
        else:
            flush_list()
            para.append(line.strip())
        i += 1
    flush_para()
    flush_list()
    return "\n".join(blocks)
