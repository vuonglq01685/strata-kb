"""CSS / SCSS custom-property scanning for `_symbols_lang`: blank out what
can hold a `--x:` lookalike (comments, strings, `url(..)`, `@supports`), then
read `--name` at declaration position. Split from `_symbols_lang` to keep
that module under the file-size ceiling."""

from __future__ import annotations

import re
from bisect import bisect_left

__all__ = ["DYNAMIC_PROP", "PROPERTY_AT_RULE", "clean_style", "declarations"]

_BLOCK_COMMENT = re.compile(rb"/\*.*?\*/", re.S)
_STRING = re.compile(rb""""(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'""")
_URL = re.compile(rb"url\([^)\n]*\)", re.I)
_SUPPORTS = re.compile(rb"@supports[^{;]*")
_LINE_COMMENT = re.compile(rb"//[^\n]*")
_CUSTOM_PROP = re.compile(rb"(?<![\w-])(--[\w-]+)\s*:")
PROPERTY_AT_RULE = re.compile(rb"@property\s+(--[\w-]+)")
DYNAMIC_PROP = re.compile(rb"(?<![\w-])--[\w-]*#\{")


def _blank(pattern: re.Pattern[bytes], text: bytes) -> bytes:
    # same line count, so line numbers survive
    return pattern.sub(lambda m: re.sub(rb"[^\n]", b" ", m.group(0)), text)


def clean_style(source: bytes, scss: bool) -> bytes:
    """`source` with everything that can hold a `--x:` lookalike blanked:
    comments, strings, `url(..)`, `@supports (..)` conditions."""
    text = _blank(_BLOCK_COMMENT, source)
    for pattern in (_STRING, _URL, _SUPPORTS, *([_LINE_COMMENT] if scss else [])):
        text = _blank(pattern, text)
    return text


def declarations(text: bytes) -> list[bytes]:
    """`--name` at declaration position: after `{`, `;`, `}` or the start,
    outside parentheses (so a map key inside a value is not one)."""
    opens = [m.start() for m in re.finditer(rb"\(", text)]
    closes = [m.start() for m in re.finditer(rb"\)", text)]
    found = []
    for m in _CUSTOM_PROP.finditer(text):
        start = m.start(1)
        i = start
        while i > 0 and text[i - 1 : i].isspace():
            i -= 1
        before = text[i - 1 : i] if i else b""
        depth = bisect_left(opens, start) - bisect_left(closes, start)
        if depth <= 0 and before in (b"", b"{", b";", b"}"):
            found.append(m.group(1))
    return found
