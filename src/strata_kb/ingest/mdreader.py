"""mdreader — turn a Markdown file into the `DocItem` stream the sectioner
reads, without docling.

Only heading lines are interpreted; every other top-level block keeps its
exact source lines, so L3 carries the author's bytes. Pages are synthetic:
one per top-level heading block, so the page checks have something to cite.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml
from markdown_it import MarkdownIt

from strata_kb.ingest.sectioner import DocItem, parse_section_id
from strata_kb.l3check.detect import strip_markdown

_KINDS = {
    "paragraph_open": "text",
    "html_block": "text",
    "blockquote_open": "text",
    "hr": "text",
    "table_open": "table",
    "fence": "code",
    "code_block": "code",
    "bullet_list_open": "list",
    "ordered_list_open": "list",
}
_FENCED_HEADING = re.compile(r"^#{2,3} ")
# emphasis or a link wrapping the leading id token (`**1.2** Scope`,
# `[1.2](u) Scope`) or the whole heading (`**1.2 Scope**`)
_LEAD_WRAP = re.compile(r"^(?:(\*\*|__|\*|_)(\S+?)\1|\[([^\]\s]+)\]\([^)]*\))(?=\s|$)")
_WHOLE_WRAP = re.compile(r"^(\*\*|__|\*|_)(.+)\1$")


@dataclass(frozen=True)
class MdDoc:
    items: list[DocItem]
    title: str | None
    warnings: list[str]


@dataclass(frozen=True)
class _Parsed:
    items: list[DocItem]
    title: str | None
    warnings: list[str]
    lines: list[str]
    page_starts: list[int]  # source line index where each page begins


def _normalize(text: str) -> str:
    return text.removeprefix("﻿").replace("\r\n", "\n").replace("\r", "\n")


def _drop_front_matter(lines: list[str]) -> tuple[list[str], int]:
    if lines and lines[0].rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                try:
                    meta = yaml.safe_load("\n".join(lines[1:i]))
                except (yaml.YAMLError, ValueError):  # e.g. a malformed timestamp
                    return lines, 0
                # a thematic break + setext `Title\n---` is not front matter
                return (lines[i + 1 :], i + 1) if isinstance(meta, dict) else (lines, 0)
    return lines, 0


def _heading_text(inline_content: str) -> str:
    text = " ".join(inline_content.split())
    if m := _LEAD_WRAP.match(text):
        unwrapped = (m.group(2) or m.group(3)) + text[m.end() :]
    elif m := _WHOLE_WRAP.match(text):
        unwrapped = m.group(2)
    else:
        return text
    # unwrap only markup that wraps an id: title words stay as written
    parsed = parse_section_id(unwrapped)
    if not parsed:
        return text
    # ids are normalized (`1.2.` -> `1.2`, `2.0` -> `2`): compare the token's own id
    token = parse_section_id(unwrapped.split()[0] + " x")
    return unwrapped if token and token[0] == parsed[0] else text


def _refuse_fenced_headings(
    tokens: list, lines: list[str], offset: int, name: str
) -> None:
    bad = [
        n + offset + 1
        for t in tokens
        if t.level == 0 and t.type in ("fence", "code_block", "html_block") and t.map
        for n in range(*t.map)
        if _FENCED_HEADING.match(lines[n])
    ]
    if bad:
        raise ValueError(
            f"{name}: fenced code holds a '## ' heading line at line(s) "
            f"{', '.join(map(str, bad))} — move it out of the fence or indent it"
        )


def _gap_blocks(tokens: list, lines: list[str]) -> list[tuple[int, DocItem]]:
    """Non-blank lines no top-level token maps (link reference definitions)
    become verbatim text items, so no source content misses L3."""
    covered = {n for t in tokens if t.level == 0 and t.map for n in range(*t.map)}
    out: list[tuple[int, DocItem]] = []
    run: list[int] = []
    for n in [*range(len(lines)), len(lines)]:
        if n < len(lines) and n not in covered and lines[n].strip():
            run.append(n)
        elif run:
            out.append((run[0], DocItem("text", "\n".join(lines[run[0] : n]))))
            run = []
    return out


def _parse(text: str, name: str) -> _Parsed:
    lines, offset = _drop_front_matter(_normalize(text).split("\n"))
    warnings = [f"front matter dropped ({offset} lines)"] if offset else []
    tokens = MarkdownIt("commonmark").enable("table").parse("\n".join(lines))
    _refuse_fenced_headings(tokens, lines, offset, name)

    blocks: list[tuple[int, DocItem]] = []  # (first source line, item)
    for i, t in enumerate(tokens):
        if t.level != 0 or not t.map:
            continue
        if t.type == "heading_open":
            item = DocItem(
                "heading", _heading_text(tokens[i + 1].content), level=int(t.tag[1])
            )
        elif t.type in _KINDS:
            kind = _KINDS[t.type]
            if t.type == "paragraph_open":
                kids = tokens[i + 1].children or []
                if len(kids) == 1 and kids[0].type == "image":
                    kind = "image"
            body = "\n".join(lines[t.map[0] : t.map[1]]).rstrip("\n")
            item = DocItem(kind, body)
        else:
            continue
        blocks.append((t.map[0], item))

    blocks += _gap_blocks(tokens, lines)
    blocks.sort(key=lambda b: b[0])

    h1 = [it for _, it in blocks if it.kind == "heading" and it.level == 1]
    title = None
    if len(h1) == 1 and parse_section_id(h1[0].text) is None:
        title = h1[0].text
        blocks = [(s, it) for s, it in blocks if it is not h1[0]]

    levels = [it.level for _, it in blocks if it.kind == "heading"]
    top = min(levels, default=0)
    page, page_starts, items, seen_top = 1, [0], [], False
    for start, it in blocks:
        if it.kind == "heading" and it.level == top:
            if seen_top:
                page += 1
                page_starts.append(start)
            seen_top = True
        items.append(DocItem(it.kind, it.text, it.level, page))
    return _Parsed(items, title, warnings, lines, page_starts)


def read_md(text: str, name: str) -> MdDoc:
    p = _parse(text, name)
    return MdDoc(p.items, p.title, p.warnings)


def md_pages(text: str) -> dict[int, str]:
    p = _parse(text, "")
    ends = [*p.page_starts[1:], len(p.lines)]
    return {
        n: strip_markdown("\n".join(p.lines[s:e]))
        for n, (s, e) in enumerate(zip(p.page_starts, ends, strict=True), start=1)
    }
