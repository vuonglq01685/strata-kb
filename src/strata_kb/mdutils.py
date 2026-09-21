from __future__ import annotations

import re
import unicodedata

import tiktoken

from strata_kb import models

_ENCODER = None

HEADING_RE = re.compile(r"^## (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")
_HEADING_RE = HEADING_RE  # back-compat alias — callers import this private name directly
_SEP_ROW_RE = re.compile(r"^\|[\s:|-]+\|$")
_FENCE_RE = re.compile(r"^(`{3,}|~{3,})")


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def slugify_id(text: str) -> str:
    """Unicode-aware slug for section ids: keep letters/digits of every
    script (slugify() drops non-ASCII entirely — CJK/Cyrillic titles would
    vanish). File names keep using slugify(); this is for ids only."""
    text = unicodedata.normalize("NFKC", text)
    slug = re.sub(r"[\W_]+", "-", text).strip("-").lower()
    return slug[:40].rstrip("-")


def count_tokens(text: str) -> int:
    global _ENCODER
    if _ENCODER is None:
        _ENCODER = tiktoken.get_encoding("cl100k_base")
    return len(_ENCODER.encode(text))


def slice_section(md: str, section_id: str, occurrence: int = 0) -> str | None:
    """Slice the `occurrence`-th (0-based) '## <section_id> ...' heading's
    body. Manifest section ids are not required to be unique within a file
    (spec allows repeated numbering); `occurrence=0` (default) keeps the
    original first-match behavior byte-for-byte."""
    lines = md.splitlines()
    seen = -1
    start = None
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            seen += 1
            if seen == occurrence:
                start = i
                break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


def heading_occurrences(sections: list[models.SectionEntry]) -> list[int]:
    """0-based occurrence index of each section's (file, id) pair, counted
    over ALL rows in manifest order — result[i] lines up with sections[i].
    Ids are not unique within a file, so a caller resolving a manifest row
    to its heading (via `slice_section(..., occurrence=n)`) or its L2
    marker (via a marker-occurrence-aware writer) needs this to know which
    occurrence a given row is, independent of section status."""
    seen: dict[tuple[str, str], int] = {}
    out: list[int] = []
    for sec in sections:
        key = (sec.file, sec.id)
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        out.append(occurrence)
    return out


_SUBHEADING_RE = re.compile(r"^### (?P<sid>\S+)(?:[ \t]+(?P<title>.*?))?\s*$")


def slice_subsection(md: str, section_id: str) -> str | None:
    """Slice a folded child ('### <id> <title>' inside a unit body) — ends at
    the next '###'/'##' heading. slice_section() only addresses '## ' units;
    folded children need this."""
    lines = md.splitlines()
    start = None
    for i, line in enumerate(lines):
        m = _SUBHEADING_RE.match(line)
        if m and m.group("sid") == section_id:
            start = i
            break
    if start is None:
        return None
    for j in range(start + 1, len(lines)):
        if lines[j].startswith(("## ", "### ")):
            return "\n".join(lines[start:j]).strip()
    return "\n".join(lines[start:]).strip()


def _unfenced_lines(md: str):
    """Yield each line of `md` that lies outside a ``` / ~~~ fence (opened
    and closed by a run of 3+ of the same fence char). Fence marker lines
    themselves are never yielded, and an unclosed fence swallows every
    line after it -- shared by `_iter_headings(fence_aware=True)` and
    `extract_tables()` so a fenced code block embedding a heading-shaped
    or table-shaped line (a `.raw.md` quoting a source file) is never
    mistaken for real document structure (Ruling R16)."""
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in md.splitlines():
        stripped = line.strip()
        m = _FENCE_RE.match(stripped)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence, fence_char, fence_len = True, marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
            continue
        if in_fence:
            continue
        yield line


def extract_tables(md: str) -> list[str]:
    tables: list[str] = []
    current: list[str] = []
    for line in list(_unfenced_lines(md)) + [""]:
        if line.lstrip().startswith("|"):
            current.append(line.strip())
        else:
            if len(current) >= 1:
                tables.append("\n".join(current))
            current = []
    return tables


def _iter_headings(md: str, *, fence_aware: bool):
    """Yield each real `## <id> …` heading match, in file order.

    fence_aware=True tracks fences via `_unfenced_lines()` and never yields
    a match for a '## ' line that falls inside one -- a `.raw.md` embedding
    a source file whose own text happens to contain a Markdown heading line
    is not a document heading (Ruling R16)."""
    lines = _unfenced_lines(md) if fence_aware else md.splitlines()
    for line in lines:
        m = HEADING_RE.match(line)
        if m:
            yield m


def heading_ids(md: str, *, fence_aware: bool = False) -> list[str]:
    """Section ids of every `## <id> …` heading, in file order.

    fence_aware=True (default False, back-compat) skips headings inside a
    fenced code block -- see `_iter_headings()`."""
    return [m.group("sid") for m in _iter_headings(md, fence_aware=fence_aware)]


def heading_id_titles(md: str, *, fence_aware: bool = False) -> list[tuple[str, bool]]:
    """Like `heading_ids()`, but pairs each id with whether the heading
    carries a title (a second, whitespace-separated token after
    '## <id>'). A title-less heading ('## Ownership') is the same shape as
    codeingest's human 'free-form single-word subheading'
    (codeingest/core.py:839, `_slice_known_section`) -- callers use this to
    tell that apart from a real, titled scaffold heading (Ruling R16)."""
    out: list[tuple[str, bool]] = []
    for m in _iter_headings(md, fence_aware=fence_aware):
        title = m.group("title")
        out.append((m.group("sid"), bool(title and title.strip())))
    return out


def orphan_heading_ids(text: str, suffix: str, known_ids: set[str]) -> list[str]:
    """Ids of every real `## <id> …` heading in one L2 (`.md`) or L3
    (`.raw.md`) file body that is NOT a known manifest id.

    The shared predicate behind `kb build`'s orphan-heading check
    (`build._check_orphan_headings`) and `kb doctor`'s (`doctor._check_doc`)
    -- they must never diverge on it again (fix round 1, Critical 2: doctor
    used to skip the exemption below and flagged a KB `kb build` calls
    clean). `suffix` is the caller's literal ".md"/".raw.md" loop variable:
    the one exemption is L2-only -- a title-less heading ('## Ownership', a
    single token, no title) in the L2 `.md` is a human's own free-form
    subheading, not a scaffold section break (Ruling R16), mirroring
    codeingest's own `_slice_known_section` reader. `.raw.md` gets no such
    exemption; a title-less heading there is still an orphan."""
    out = []
    for sid, has_title in heading_id_titles(text, fence_aware=True):
        if sid in known_ids:
            continue
        if suffix == ".md" and not has_title:
            continue  # human free-form subheading, e.g. '## Ownership'
        out.append(sid)
    return out


_IMAGE_MD_RE = re.compile(r"!\[([^\]]*)\]\(assets/[0-9a-f]{64}\.(?:png|webp)\)")


def extract_image_descs(md: str) -> list[str]:
    """Alt-texts of standalone image refs, in order, deduped, blanks dropped.

    Table rows are skipped: table icons already reach L2 inside the copied
    table, byte-identical — they must not also become 'Figure:' lines.
    """
    descs: list[str] = []
    for line in md.splitlines():
        if line.lstrip().startswith("|"):
            continue
        for m in _IMAGE_MD_RE.finditer(line):
            alt = m.group(1).strip()
            if alt and alt not in descs:
                descs.append(alt)
    return descs


def normalize_table(table_md: str) -> str:
    rows: list[str] = []
    for line in table_md.splitlines():
        line = line.strip()
        if not line or _SEP_ROW_RE.match(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append("|".join(" ".join(c.split()) for c in cells))
    return "\n".join(rows)
