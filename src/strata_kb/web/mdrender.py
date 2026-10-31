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
_LIST_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-*]|\d+[.)])[ \t]+(?P<text>.*)$")
_NEST_INDENT = 2  # spaces more than the parent item that open a nested list
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


class _ListBuilder:
    """One open list: level-1 items, each with nested level-2 lists. Deeper
    indents stay at level 2; a tab counts as 4 spaces."""

    def __init__(self, terms: set[str]) -> None:
        self.terms = terms
        self._reset()

    def _reset(self) -> None:
        self.kind = ""  # "ul" | "ol"; "" = no list open
        self.base = 0
        # (text parts, [(kind, [text parts per item])])
        self.items: list[tuple[list[str], list[tuple[str, list[list[str]]]]]] = []
        self.last: list[str] = []

    def add(self, m: re.Match[str]) -> str | None:
        """Add an item; returns the finished list's HTML when a level-1
        marker type change closes it."""
        indent = len(m.group("indent").expandtabs(4))
        kind = "ol" if m.group("marker")[0].isdigit() else "ul"
        text = [m.group("text").strip()]
        if self.items and indent >= self.base + _NEST_INDENT:
            subs = self.items[-1][1]
            if not subs or subs[-1][0] != kind:
                subs.append((kind, []))
            subs[-1][1].append(text)
            self.last = text
            return None
        done = self.flush() if self.kind and kind != self.kind else None
        if not self.kind:
            self.kind, self.base = kind, indent
        self.items.append((text, []))
        self.last = text
        return done

    def continues(self, line: str) -> bool:
        """An indented non-item line inside an open list joins the last item."""
        if (
            not self.kind
            or len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip()) < 2
        ):
            return False
        self.last.append(line.strip())
        return True

    def flush(self) -> str | None:
        if not self.kind:
            return None

        def li(parts: list[str]) -> str:
            return _inline(" ".join(parts), self.terms)

        out = []
        for text, subs in self.items:
            nested = "".join(
                f"<{k}>" + "".join(f"<li>{li(t)}</li>" for t in sub) + f"</{k}>"
                for k, sub in subs
            )
            out.append(f"<li>{li(text)}{nested}</li>")
        html_out = f"<{self.kind}>{''.join(out)}</{self.kind}>"
        self._reset()
        return html_out


def render(md: str, terms: set[str] | None = None) -> str:
    terms = terms or set()
    blocks: list[str] = []
    para: list[str] = []
    lists = _ListBuilder(terms)

    def flush_para() -> None:
        if para:
            blocks.append(f"<p>{_inline(' '.join(para), terms)}</p>")
            para.clear()

    def flush_list() -> None:
        done = lists.flush()
        if done:
            blocks.append(done)

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
            done = lists.add(m_li)
            if done:
                blocks.append(done)
        elif not line.strip():
            flush_para()  # a blank line does not end a list
        elif not para and lists.continues(line):
            pass
        else:
            flush_list()
            para.append(line.strip())
        i += 1
    flush_para()
    flush_list()
    return "\n".join(blocks)
