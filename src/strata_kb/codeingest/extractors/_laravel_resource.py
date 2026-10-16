"""The routes `Route::resource()` and `Route::apiResource()` expand to.

`Route::resource('photos.comments', X::class)` is the seven standard
actions on `photos/{photo}/comments`; `apiResource` has no `create` and
`edit`; `update` answers PUT and PATCH, so it is two routes. The wildcard of
a segment is its singular (`Str::singular` in Laravel, a few English rules
here), with `-` read as `_`.
"""

from __future__ import annotations

__all__ = ["API", "FULL", "expand"]

FULL: tuple[str, ...] = (
    "index",
    "create",
    "store",
    "show",
    "edit",
    "update",
    "destroy",
)
API: tuple[str, ...] = ("index", "store", "show", "update", "destroy")
_IRREGULAR = {
    "people": "person", "children": "child", "men": "man", "women": "woman",
    "feet": "foot", "teeth": "tooth", "geese": "goose", "mice": "mouse",
}  # fmt: skip


def singular(word: str) -> str:
    low = word.lower()
    if low in _IRREGULAR:
        return _IRREGULAR[low]
    for end, back in (("ies", "y"), ("sses", "ss"), ("uses", "us"), ("xes", "x"),
                      ("ches", "ch"), ("shes", "sh"), ("zzes", "z")):  # fmt: skip
        if low.endswith(end) and len(low) > len(end):
            return word[: -len(end)] + back
    if low.endswith(("ss", "us", "is")) or not low.endswith("s"):
        return word
    return word[:-1]


def _wildcard(segment: str) -> str:
    return singular(segment.rsplit("/", 1)[-1]).replace("-", "_")


def expand(name: str, actions: list[str]) -> list[tuple[str, str, str]] | None:
    """(action, method, uri) of each route, None for an empty name."""
    segments = [s for s in name.strip("/").split(".") if s]
    if not segments:
        return None
    nested = "".join(f"{s}/{{{_wildcard(s)}}}/" for s in segments[:-1])
    collection = nested + segments[-1]
    member = f"{collection}/{{{_wildcard(segments[-1])}}}"
    table = {
        "index": [("GET", collection)],
        "create": [("GET", f"{collection}/create")],
        "store": [("POST", collection)],
        "show": [("GET", member)],
        "edit": [("GET", f"{member}/edit")],
        "update": [("PUT", member), ("PATCH", member)],
        "destroy": [("DELETE", member)],
    }
    return [(a, m, u) for a in actions for m, u in table[a]]
