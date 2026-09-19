"""api extractor -- `api.<tag>` sections from a committed OpenAPI/Swagger
document's `paths`.

A single document may describe many operations across many tags; this
module groups every `paths.<path>.<method>` operation by its first `tags`
entry (or the literal string `"surface"` when an operation carries no tag
at all, or an empty/blank one) and emits one `CodeSection` per tag. Every
operation's own HTTP method and path are genuine, structural facts read
straight off the document -- nothing here infers or guesses a route that
isn't literally declared.

**Security (never a secret channel, spec §3.11) -- the one sanctioned
exception, and its limit (task review, Important 2).** An OpenAPI/Swagger
document is committed source, not a runtime secret store: unlike a `.env`
file or a compose `environment:` block (which may only ever contribute
*key names*, never values -- `integrations.py` in this same task enforces
that), this module reads and emits `servers[*].url` **as the literal URL
text**. That is deliberate and the *only* place in either of this task's
two extractors where a raw string value, not just a sanitised key name,
reaches rendered output -- because a server URL's host and path,
describing where a committed, public API contract is hosted, is already
public information, not a secret. That is **not** true of the URL's own
userinfo segment: a `user:pass@`/`token@` a Dev committed to the document
in plaintext is a credential, not a routing fact, so `_extract_servers`
runs every URL through the shared `redact_userinfo` (`_envkeys.py`)
before it is kept -- the host/path exemption stands, the userinfo one
never existed. Nothing else in this module (or in `integrations.py`) is
exempted the same way.

**Degrade, never crash.** A parse failure, or a wrong-shaped document at
any level (`paths:` a list, an operation that's a string, `servers:` a
mapping), is a warning naming the file; every other file this extractor
finds still contributes its own sections (matching deps.py/services.py/
schema.py's discipline).

**Tag-id collisions never abort the run (Important review finding).**
`CodeSection.id` must be unique across the whole extractor set --
`core.run()` raises a fatal `CodeIngestError` on any duplicate, which
would abort the entire `kb code-ingest` command with no KB written at
all. Two distinct tags that differ only in whitespace-vs-hyphen shape
(`"My Tag"` and `"My-Tag"`) both produce `_safe_tag_id` `"My-Tag"` and
would previously have collided. `_read_openapi` therefore groups
operations by **tag id**, not raw tag text, from the start; every raw
tag spelling that maps to a given id is tracked in `raw_tags_by_id` so a
genuine collision can be (a) warned about and (b) rendered as one merged
section with a deterministic, name-derived display tag (the
lexicographically smallest of the colliding spellings) -- never a
crash. Merging, rather than inventing a disambiguating suffix the way
`services.py` does for the analogous service-name collision (Rulings
R30/R31), was chosen because `services.py`'s `svc.<name>` id is a
public join key Stage C's `kb svc note` depends on staying unique per
service -- `api.<tag>` carries no such downstream stability contract,
so the extra complexity of a hash-suffix scheme isn't justified for
what both the reviewer and this module's author agree is a very
unlikely input shape.

**`ApiExtractor.detect(self, root)` cannot see `opts.kb_dir`** -- the same
structural exception `deps.py`, `commands.py`, and `schema.py` document:
the `Extractor` protocol's `detect()` is never passed `opts`, so
`find_openapi_files()` is called with `kb_dir=None` there; `extract()`
threads `opts.kb_dir` through (Ruling R24).
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

import yaml

from strata_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult
from strata_kb.codeingest.extractors._envkeys import redact_userinfo
from strata_kb.codeingest.extractors._mdcells import escape_cell
from strata_kb.codeingest.extractors.tree import relposix, walk_tree

# A pattern with no "**/" prefix only matches at the repository root
# (depth 0) -- the shape a plain `root.glob(pattern)` call would have had.
# The one "**/"-prefixed pattern matches its trailing filename glob at any
# depth. Both shapes are resolved through `find_openapi_files()` below,
# via `walk_tree`'s pruned, deterministic traversal -- never
# rglob/glob/os.walk (Ruling R7).
API_GLOBS: tuple[str, ...] = (
    "openapi*.y*ml", "openapi*.json", "swagger*.y*ml", "swagger*.json", "**/openapi*.y*ml",
)

_METHODS: tuple[str, ...] = ("get", "post", "put", "patch", "delete", "head", "options")


def find_openapi_files(root: Path, kb_dir: Path | None) -> list[Path]:
    """Resolve `API_GLOBS` into matching files under `root`, through the
    one pruned, deterministic `walk_tree` traversal (Ruling R7) instead of
    a hand-rolled `rglob`/`glob`/`os.walk`. Exposed (not underscore-
    prefixed) so `integrations.py`'s `detect()` can ask "is there a
    committed OpenAPI/Swagger file here" without re-implementing this
    same mixed root-only/any-depth glob resolution a second time --
    exactly the kind of duplicated logic that let Task B4's secret leak
    survive two rounds of "fix the reported branch" before a shared
    helper closed it for good.
    """
    matches: set[Path] = set()
    for depth, reldir, filenames in walk_tree(root, kb_dir):
        for pattern in API_GLOBS:
            if pattern.startswith("**/"):
                file_glob = pattern[3:]
            else:
                if depth != 0:
                    continue
                file_glob = pattern
            for name in filenames:
                if fnmatch.fnmatch(name, file_glob):
                    matches.add(root / reldir / name)
    return sorted(matches, key=lambda p: relposix(root, p))


@dataclass
class _Operation:
    path: str
    method: str  # already upper-cased
    summary: str
    source: str  # relposix of the file this operation came from


def _op_tag(op: dict) -> str:
    """The brief's rule verbatim: the first entry of `tags`, or the
    literal string `"surface"`. An empty/blank first tag, or a `tags`
    list that isn't a list of strings, is treated the same as "no tags at
    all" -- rather than fabricating a section id from a blank or
    non-string value."""
    tags = op.get("tags")
    if isinstance(tags, list) and tags:
        first = tags[0]
        if isinstance(first, str) and first.strip():
            return first
    return "surface"


def _safe_tag_id(tag: str) -> str:
    """`CodeSection.id` must contain no whitespace (`mdutils._HEADING_RE`)
    -- an OpenAPI tag is free-text and could in principle contain spaces,
    even though every tag in this task's own fixtures is already a bare
    identifier. Collapsing whitespace to `-` and falling back to
    `"surface"` for a tag that collapses away to nothing keeps `api.<tag>`
    always a valid id without changing the common case at all.

    Not injective: `"My Tag"` and `"My-Tag"` both collapse to `"My-Tag"`.
    `_read_openapi`/`_render_section` handle that collision by merging
    (see module docstring) rather than by strengthening this function --
    a stronger encoding here would just move the same ambiguity into the
    id text itself, which is exactly what this function exists to keep
    readable."""
    collapsed = "-".join(tag.split())
    return collapsed if collapsed else "surface"


def _display_tag(tag: str) -> str:
    """Rendered `title` text -- collapse any whitespace run (including a
    literal newline) to a single space, so a tag containing one can never
    split the rendered `"## <id> <title>"` heading into two lines (Minor
    review finding: an OpenAPI tag is free text an author could have
    typed with an embedded newline). Unlike `_safe_tag_id`, this doesn't
    hyphenate -- `title` is prose, it only needs to stay one line."""
    collapsed = " ".join(tag.split())
    return collapsed if collapsed else "surface"


def _extract_servers(data: dict, rel: str, warnings: list[str]) -> list[str]:
    """`servers[*].url` from one already-parsed OpenAPI document --
    literal URL strings, the one sanctioned exception to "never emit a
    value" (see module docstring). A wrong-shaped `servers` (present but
    not a list -- a mapping, a string, `null`, ...) warns naming the
    file; an *absent* `servers` key is normal and does not warn. Checking
    `"servers" in data` first (rather than `.get("servers", [])` then a
    truthiness check) is what makes that distinction correct -- a
    truthiness check alone would let a wrong-shaped-but-falsy value like
    `servers: {}` slip through silently while `servers: {url: ...}` warned
    (Minor review finding). A list entry that isn't a mapping with a
    string `url` is skipped without its own warning -- one entry's shape
    doesn't invalidate the whole (correctly-typed) list."""
    if "servers" not in data:
        return []
    servers_raw = data["servers"]
    urls: list[str] = []
    if isinstance(servers_raw, list):
        for entry in servers_raw:
            if isinstance(entry, dict):
                url = entry.get("url")
                if isinstance(url, str) and url:
                    # `redact_userinfo` (task review, Important 2): a
                    # committed `servers[*].url` may carry a `user:pass@`
                    # or bare `token@` credential -- a server URL's host
                    # and path are public information about a committed
                    # API contract, but userinfo is not, and .kb/'s
                    # _snapshot republishes this to the federation hub.
                    urls.append(redact_userinfo(url))
    else:
        warnings.append(f"could not parse {rel}: 'servers' is not a list")
    return urls


def _read_openapi(
    root: Path, kb_dir: Path | None
) -> tuple[dict[str, list[_Operation]], dict[str, set[str]], dict[str, set[str]], list[str]]:
    """Every OpenAPI/Swagger file `find_openapi_files` locates, parsed
    with `yaml.safe_load` (YAML is a JSON superset, so one loader covers
    both `.yaml`/`.yml` and `.json`). Returns `(ops_by_id, servers_by_id,
    raw_tags_by_id, warnings)`, all keyed by **tag id**
    (`_safe_tag_id(tag)`), not raw tag text -- see the module docstring's
    "Tag-id collisions never abort the run" section for why.
    `raw_tags_by_id[tag_id]` is every distinct raw tag spelling that
    mapped to that id (almost always exactly one). `servers_by_id[tag_id]`
    is the union of every server URL declared by a file that contributed
    at least one operation under that id. A malformed file, or a
    wrong-shaped `paths`/path-item/operation at any level, warns naming
    the file and is skipped; every other file (and every other
    path/operation in the same file) still contributes."""
    ops_by_id: dict[str, list[_Operation]] = {}
    servers_by_id: dict[str, set[str]] = {}
    raw_tags_by_id: dict[str, set[str]] = {}
    warnings: list[str] = []

    for path in find_openapi_files(root, kb_dir):
        rel = relposix(root, path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
        if not isinstance(data, dict):
            warnings.append(f"could not parse {rel}: top-level is not a mapping")
            continue

        file_servers = _extract_servers(data, rel, warnings)

        paths_raw = data.get("paths", {})
        if not isinstance(paths_raw, dict):
            warnings.append(f"could not parse {rel}: 'paths' is not a mapping")
            continue

        for path_key, path_item in paths_raw.items():
            if not isinstance(path_item, dict):
                warnings.append(f"could not parse {rel}: path {path_key!r} is not a mapping")
                continue
            for method in _METHODS:
                if method not in path_item:
                    continue
                op = path_item[method]
                if not isinstance(op, dict):
                    warnings.append(
                        f"could not parse {rel}: operation "
                        f"{method.upper()} {path_key!r} is not a mapping"
                    )
                    continue
                summary = op.get("summary", "")
                if not isinstance(summary, str):
                    summary = ""
                tag = _op_tag(op)
                tag_id = _safe_tag_id(tag)
                ops_by_id.setdefault(tag_id, []).append(
                    _Operation(
                        path=str(path_key), method=method.upper(),
                        summary=summary, source=rel,
                    )
                )
                servers_by_id.setdefault(tag_id, set()).update(file_servers)
                raw_tags_by_id.setdefault(tag_id, set()).add(tag)

    for tag_id, raw_tags in raw_tags_by_id.items():
        if len(raw_tags) > 1:
            warnings.append(
                f"tags {sorted(raw_tags)} all collapse to the same section id "
                f"'api.{tag_id}'; merging their operations into one section"
            )

    return ops_by_id, servers_by_id, raw_tags_by_id, warnings


def _render_section(
    tag_id: str, display_tag: str, ops: list[_Operation], servers: set[str]
) -> CodeSection:
    # Brief's rule: group operations by tag, sorted by (path, method) --
    # extended with (source, summary) as a tiebreak (Minor review
    # finding) so the key is total for two operations sharing one
    # (path, method) under the same tag id but declared in different
    # files: without it, output order for that tie depended on
    # `sorted()`'s stability plus the *incidental* fact that this
    # module's own input ordering (sorted file list, in-file YAML
    # mapping order) already happened to be deterministic -- exactly the
    # kind of implicit invariant this stage has been burned by before.
    ops_sorted = sorted(ops, key=lambda o: (o.path, o.method, o.source, o.summary))
    servers_str = ", ".join(sorted(servers)) if servers else "none declared"

    l2_lines = [
        f"**Servers:** {escape_cell(servers_str)}",
        "",
        "| Method | Path | Summary |",
        "| --- | --- | --- |",
    ]
    l2_lines.extend(
        f"| {escape_cell(o.method)} | {escape_cell(o.path)} | {escape_cell(o.summary)} |"
        for o in ops_sorted
    )
    l2_md = "\n".join(l2_lines) + "\n"

    l3_lines = [f"{o.method} {o.path} — {o.summary}" for o in ops_sorted]
    l3_md = "```\n" + "\n".join(l3_lines) + "\n```\n"

    methods = ", ".join(sorted({o.method for o in ops_sorted}))
    files = ", ".join(sorted({o.source for o in ops_sorted}))
    # Sanitised once, used for both title and summary -- round 2 review
    # finding: title went through `_display_tag` but summary still
    # interpolated the raw `display_tag`, so a tag containing a literal
    # newline reached `summary` (and, via core.run(), _manifest.yaml)
    # unsanitised even though the same newline could no longer split the
    # rendered heading. Same field-sanitisation rule, applied to the one
    # field the previous round missed.
    clean_tag = _display_tag(display_tag)
    summary = f"API tag {clean_tag}: {len(ops_sorted)} operations ({methods}) from {files}."

    return CodeSection(
        id=f"api.{tag_id}",
        title=clean_tag,
        summary=summary,
        group="api",
        l2_md=l2_md,
        l3_md=l3_md,
    )


class ApiExtractor:
    name = "api"

    def detect(self, root: Path) -> bool:
        # No `opts` at detect() time -- see module docstring.
        return bool(find_openapi_files(root, None))

    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult:
        try:
            ops_by_id, servers_by_id, raw_tags_by_id, warnings = _read_openapi(
                root, opts.kb_dir
            )
        except Exception as exc:  # noqa: BLE001 -- defense in depth: must never crash extract()
            return ExtractResult(
                sections=[], warnings=[f"could not read OpenAPI/Swagger sources: {exc}"]
            )

        sections = [
            _render_section(
                tag_id,
                sorted(raw_tags_by_id[tag_id])[0],  # deterministic: lexicographically first
                ops_by_id[tag_id],
                servers_by_id.get(tag_id, set()),
            )
            for tag_id in sorted(ops_by_id)
        ]
        return ExtractResult(sections=sections, warnings=warnings)
