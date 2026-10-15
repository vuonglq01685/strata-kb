"""The path Symfony registers for a route written with inline syntax.

`/{_locale<en|fr>?en}/page/{page<\\d+>?1}` is registered as
`/{_locale}/page/{page}`: the `<requirement>` and `?default` parts of a
placeholder are compiled into a requirement and a default value, not into
the path (`debug:router` shows the short form). The short form also keeps
`|`, regex text and default values out of the Path column.
"""

from __future__ import annotations

import re

__all__ = ["compiled"]

_NAME = re.compile(r"[A-Za-z_][\w:]*")


def compiled(path: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(path):
        if path[i] != "{":
            out.append(path[i])
            i += 1
            continue
        depth, j = 1, i + 1
        while j < len(path) and depth:
            depth += (path[j] == "{") - (path[j] == "}")
            j += 1
        if depth:  # unbalanced: leave the rest as written
            out.append(path[i:])
            break
        inner = path[i + 1 : j - 1]
        name = _NAME.match(inner)
        if name and inner[name.end() : name.end() + 1] in ("", "<", "?"):
            out.append("{" + name.group(0) + "}")
        else:
            out.append(path[i:j])
        i = j
    return "".join(out)
