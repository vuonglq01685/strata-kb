"""GitHub-flavoured markdown→HTML for BA mission and ticket pages.

`mdrender` stays the renderer for L2/L3 reference sections (tables there
must render character-for-character). Missions and tickets are authored
prose, so they get what a reader sees on github.com: CommonMark + pipe
tables + strikethrough + task-list checkboxes, highlighted code, and
```mermaid fences emitted as `<pre class="mermaid">` for app.js to draw.

Raw HTML never reaches the page: html_block / html_inline tokens are
dropped after parsing (that also hides the templates' `<!-- guidance -->`
comments, as GitHub does). Link schemes go through markdown-it's own
validator (no `javascript:`).
"""

from __future__ import annotations

import html
import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pygments import highlight as _pyg_highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

_FORMATTER = HtmlFormatter(nowrap=True, classprefix="hl-")
_TASK_RE = re.compile(r"<li>(<p>)?\[([ xX])\] ")


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


_MD = MarkdownIt(
    "commonmark", {"html": True, "linkify": False, "highlight": _highlight}
).enable(["table", "strikethrough"])


def _drop_html(tokens: list[Token]) -> list[Token]:
    kept = [t for t in tokens if t.type != "html_block"]
    for t in kept:
        if t.children:
            t.children = [c for c in t.children if c.type != "html_inline"]
    return kept


def _task(m: re.Match[str]) -> str:
    box = "checked " if m.group(2) != " " else ""
    return f'<li class="task">{m.group(1) or ""}<input type="checkbox" {box}disabled> '


def render(md: str) -> str:
    tokens = _drop_html(_MD.parse(md))
    out = _MD.renderer.render(tokens, _MD.options, {})
    return _TASK_RE.sub(_task, out)


def has_mermaid(rendered: str) -> bool:
    return '<pre class="mermaid">' in rendered
