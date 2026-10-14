"""GitHub-flavoured markdown→HTML for BA mission and ticket pages.

`mdrender` stays the renderer for L2/L3 reference sections (tables there
must render character-for-character). Missions and tickets are authored
prose, so they get what a reader sees on github.com: CommonMark + pipe
tables + strikethrough + task-list checkboxes, highlighted code, and
```mermaid fences emitted as `<pre class="mermaid">` for app.js to draw.

Raw HTML never reaches the page: html is off, so a tag shows as text and
never swallows the markdown after it. Two exceptions, both safe: a
`<!-- guidance -->` comment block (the templates carry many) is hidden as
on GitHub, and `<br>` in text becomes a line break. Link schemes go through
markdown-it's own validator (no `javascript:`).
"""

from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt
from markdown_it.rules_block import StateBlock
from markdown_it.token import Token
from pygments import highlight as _pyg_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(nowrap=True, classprefix="hl-")
# a loose list item renders as `<li>\n<p>[ ] …`
_TASK_RE = re.compile(r"<li>(\n?<p>)?\[([ xX])\] ")
_BR_RE = re.compile(r"<br\s*/?>", re.I)
# planingest's published bug attachment; the hub serves it at /assets/<name>.
# Not imported: `web` stays free of the plan stack.
_ASSET_SRC_RE = re.compile(r"^assets/([0-9a-f]{64}\.(?:png|webp))$")


def _highlight(code: str, lang: str, _attrs: str) -> str:
    lang = (lang or "").strip().lower()
    if lang == "mermaid":
        return f'<pre class="mermaid">{html.escape(code)}</pre>\n'
    if not lang:
        return ""  # markdown-it escapes and wraps it
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""
    return _pyg_highlight(code, lexer, _FORMATTER)


def _comment_block(state: StateBlock, start: int, end: int, silent: bool) -> bool:
    """A block starting with `<!--` up to the line holding `-->` renders as nothing."""
    pos = state.bMarks[start] + state.tShift[start]
    if state.sCount[start] - state.blkIndent >= 4 or not state.src.startswith(
        "<!--", pos
    ):
        return False
    if silent:
        return True
    line = start
    while line < end:
        closed = "-->" in state.src[state.bMarks[line] : state.eMarks[line]]
        line += 1
        if closed:
            break
    state.line = line
    return True


_MD = MarkdownIt(
    "commonmark", {"html": False, "linkify": False, "highlight": _highlight}
).enable(["table", "strikethrough"])
_MD.block.ruler.before(
    "html_block", "comment", _comment_block, {"alt": ["paragraph", "blockquote"]}
)


def _line_breaks(children: list[Token]) -> list[Token]:
    out: list[Token] = []
    for c in children:
        if c.type != "text" or not _BR_RE.search(c.content):
            out.append(c)
            continue
        for i, part in enumerate(_BR_RE.split(c.content)):
            if i:
                out.append(Token("hardbreak", "br", 0))
            if part:
                out.append(Token("text", "", 0, content=part))
    return out


def _task(m: re.Match[str]) -> str:
    box = "checked " if m.group(2) != " " else ""
    return f'<li class="task">{m.group(1) or ""}<input type="checkbox" {box}disabled> '


def _asset_srcs(children: list[Token]) -> None:
    for c in children:
        if c.type == "image" and (m := _ASSET_SRC_RE.match(str(c.attrGet("src")))):
            c.attrSet("src", f"/assets/{m.group(1)}")


def render(md: str) -> str:
    tokens = _MD.parse(md)
    for t in tokens:
        if t.children:
            t.children = _line_breaks(t.children)
            _asset_srcs(t.children)
    out = _MD.renderer.render(tokens, _MD.options, {})
    return _TASK_RE.sub(_task, out)


def has_mermaid(rendered: str) -> bool:
    return '<pre class="mermaid">' in rendered
