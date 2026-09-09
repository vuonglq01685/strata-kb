from __future__ import annotations

import hashlib
import re
import statistics
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from center_kb import models
from center_kb.ingest.sectioner import HeadingConfig, SectionUnit
from center_kb.mdutils import count_tokens, extract_image_descs, slugify

__all__ = [
    "ScaffoldReport",
    "TokenStats",
    "chapter_stem",
    "scaffold_doc",
    "slugify",
    "token_stats",
    "validate_doc_id",
    "validate_unit_ids",
]

# Same shape as publish._REPO_ID_RE: doc_id is a directory name under .kb/,
# never a path — no separators, no leading dot.
_DOC_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_TARGET_MIN_TOKENS = 300   # phase-1 spec §4.4-3: a measured target, not a rule
_TARGET_MAX_TOKENS = 5000
_WHITESPACE_RE = re.compile(r"\s")
_PATH_SEP_RE = re.compile(r"[/\\]")


def validate_doc_id(doc_id: str) -> None:
    if not _DOC_ID_RE.fullmatch(doc_id) or doc_id in {".", ".."}:
        raise ValueError(
            f"doc id '{doc_id}' is invalid — only letters/digits/._- allowed, "
            "no path separators"
        )


def chapter_stem(chapter: str, title: str) -> str:
    prefix = _stem_prefix(chapter)
    slug = slugify(title)[:40].rstrip("-")
    return f"{prefix}-{slug}" if slug and slug != prefix else prefix


def _stem_prefix(chapter: str) -> str:
    """The part of chapter_stem() that does not depend on the title."""
    return f"ch{chapter}" if chapter and chapter[0].isdigit() else chapter


def _stem_of(filename: str) -> str:
    for suffix in (".raw.md", ".md"):
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def _belongs_to(stem: str, prefix: str) -> bool:
    return stem == prefix or stem.startswith(prefix + "-")


def _load_previous(doc_dir: Path) -> models.Manifest | None:
    path = doc_dir / "_manifest.yaml"
    return models.load_yaml_model(path, models.Manifest) if path.exists() else None


def _confirms_chapter(
    entry: models.SectionEntry, chapter: str, run_ids: set[str]
) -> bool:
    """A stem alone cannot prove which chapter it belongs to — two chapters
    can share a stem's prefix. The section id can confirm it three ways:
    it equals the chapter exactly; its leading numeric component does (the
    digits before the first '.' or '-', so '5.1', '5.1-2' and '5-2' all
    confirm chapter '5'); or it is one of THIS RUN's own ids for that
    chapter — same headings produce the same ids, so a headless appendix
    or attachment chapter (no unit's id equals the chapter id itself)
    still confirms on re-ingest."""
    if entry.id == chapter or entry.id in run_ids:
        return True
    head = re.split(r"[.-]", entry.id, maxsplit=1)[0]
    return head.isdigit() and head == chapter


def _resolve_stems(
    chapters: set[str],
    previous_sections: list[models.SectionEntry],
    units: list[SectionUnit],
) -> dict[str, str]:
    """A chapter owns exactly one file stem — every SectionEntry belonging
    to it carries the same `file`. Resolve each named chapter's stem from
    what is already on disk; a prefix can match more than one existing
    stem (the stem for chapter "appendix-a" also starts with the prefix
    for chapter "appendix"), and when it does we cannot tell which one to
    replace — refuse rather than guess and silently destroy the other.
    A prefix can also match exactly one existing stem that in fact belongs
    to a *different* chapter (e.g. a new chapter's id happens to equal or
    prefix a sibling's whole stem); a lone candidate is trusted only when
    some entry actually filed under it confirms the chapter (see
    `_confirms_chapter`, which is also given this run's own units for the
    chapter so a headless part still confirms).

    Returns `{chapter: stem}` — keyed by chapter rather than flattened to
    a set of stems, so `_merge_sections` can splice each targeted
    chapter's new entries at the position of its own former stem, even
    when a title change means the new stem is spelled differently."""
    stems: dict[str, str] = {}
    for chapter in sorted(chapters):
        prefix = _stem_prefix(chapter)
        candidates = sorted(
            {e.file for e in previous_sections if _belongs_to(e.file, prefix)}
        )
        if len(candidates) > 1:
            raise ValueError(
                f"cannot tell which files belong to chapter {chapter!r} "
                f"({', '.join(candidates)}) — re-ingest the whole document"
            )
        if candidates:
            stem = candidates[0]
            run_ids = {u.id for u in units if u.chapter == chapter}
            confirmed = any(
                e.file == stem and _confirms_chapter(e, chapter, run_ids)
                for e in previous_sections
            )
            if not confirmed:
                raise ValueError(
                    f"cannot tell whether the stem {stem!r} belongs to "
                    f"chapter {chapter!r} — re-ingest the whole document"
                )
            stems[chapter] = stem
    return stems


def _check_no_id_clash(
    units: list[SectionUnit],
    previous_sections: list[models.SectionEntry],
    stems: set[str],
) -> None:
    """The entries that survive the merge (not in `stems`) must not share
    an id with any unit this run is about to write — that would leave two
    manifest rows answering to the same address. Refuse before anything
    is deleted or written."""
    kept_ids = {e.id: e.file for e in previous_sections if e.file not in stems}
    for unit in units:
        if unit.id in kept_ids:
            raise ValueError(
                f"section id {unit.id!r} in chapter {unit.chapter!r} would "
                f"duplicate the kept entry in {kept_ids[unit.id]!r} — "
                "re-ingest the whole document"
            )


def _merge_sections(
    old: list[models.SectionEntry],
    new_by_chapter: dict[str, list[models.SectionEntry]],
    stems: dict[str, str],
) -> list[models.SectionEntry]:
    """Splice per chapter, not once for the whole merge. Each targeted
    chapter's old entries (identified by its resolved stem in `stems`)
    drop out of `old`, and that chapter's new entries take their place at
    the position of the FIRST entry dropped for it — so re-ingesting
    several non-adjacent chapters in one `--sections` run keeps every
    chapter, touched or not, in its original manifest position (a single
    shared insertion point would instead collapse them all to the first
    dropped chapter's slot, reordering everything after it). A chapter
    with no resolved stem (never ingested before) appends at the end, in
    the order scaffold_doc encountered it. Every other entry is copied
    verbatim — status, summary, tokens included."""
    stem_chapter = {stem: chapter for chapter, stem in stems.items()}
    first_index: dict[str, int] = {}
    kept: list[models.SectionEntry] = []
    for entry in old:
        chapter = stem_chapter.get(entry.file)
        if chapter is not None:
            first_index.setdefault(chapter, len(kept))
            continue
        kept.append(entry)

    ordered = sorted(first_index.items(), key=lambda kv: kv[1])
    result: list[models.SectionEntry] = []
    prev = 0
    for chapter, idx in ordered:
        result += kept[prev:idx]
        result += new_by_chapter.get(chapter, [])
        prev = idx
    result += kept[prev:]

    handled = {chapter for chapter, _ in ordered}
    for chapter, entries in new_by_chapter.items():
        if chapter not in handled:
            result += entries
    return result


@dataclass(frozen=True)
class TokenStats:
    """L3 token distribution over the sections written this run."""

    n: int
    min: int
    median: int
    max: int
    below_300: int
    above_5000: int


def token_stats(sections: list[models.SectionEntry]) -> TokenStats | None:
    counts = [s.tokens.l3 for s in sections]
    if not counts:
        return None
    return TokenStats(
        n=len(counts),
        min=min(counts),
        median=int(statistics.median(counts)),
        max=max(counts),
        below_300=sum(1 for c in counts if c < _TARGET_MIN_TOKENS),
        above_5000=sum(1 for c in counts if c > _TARGET_MAX_TOKENS),
    )


def validate_unit_ids(units: list[SectionUnit]) -> None:
    """The id is one `\\S+` token in `## <id> <title>`; slice_section() can
    never find an id with a space in it, and an empty id is no address.
    A chapter's id becomes a file stem (chapter_stem() above) — reject a
    path separator or a bare `..`/`.` segment so a crafted heading (e.g. a
    custom --chapter-pattern whose identifier group captures `../../pwn`)
    cannot write outside the document directory. Do not reuse _DOC_ID_RE
    wholesale: fallback slugs and custom-pattern ids deliberately keep
    non-ASCII scripts, which an ASCII allow-list would break."""
    for unit in units:
        if not unit.id:
            raise ValueError(
                f"section {unit.title!r} has an empty id — every unit needs an id"
            )
        if _WHITESPACE_RE.search(unit.id):
            raise ValueError(
                f"section id {unit.id!r} contains whitespace — adjust the "
                "chapter/appendix/attachment pattern so its identifier group "
                "has no spaces"
            )
        if _PATH_SEP_RE.search(unit.id) or unit.id in {".", ".."}:
            raise ValueError(
                f"section id {unit.id!r} contains a path separator or is a "
                "'..' segment — adjust the chapter/appendix/attachment "
                "pattern so its identifier group cannot produce one"
            )


@dataclass
class ScaffoldReport:
    doc_id: str
    files: list[str]
    n_sections: int
    token_stats: TokenStats | None = None


def scaffold_doc(
    units: list[SectionUnit],
    *,
    doc_id: str,
    title: str,
    tags: list[str],
    revision: str,
    source_path: Path | None,
    kb_dir: Path,
    chapters: set[str] | None = None,
    heading_config: HeadingConfig | None = None,
    part_titles: dict[str, str] | None = None,
    used_bookmarks: bool = False,
) -> ScaffoldReport:
    validate_doc_id(doc_id)
    validate_unit_ids(units)

    doc_dir = kb_dir / doc_id
    previous = _load_previous(doc_dir) if chapters is not None else None
    if chapters is not None:
        units = [u for u in units if u.chapter in chapters]
    stems: dict[str, str] = {}
    if chapters and previous is not None:
        stems = _resolve_stems(chapters, previous.sections, units)  # may raise
    resolved_old_stems = set(stems.values())
    if previous is not None:
        _check_no_id_clash(units, previous.sections, resolved_old_stems)  # may raise: id clash
    # Both checks above run before anything is deleted or written, so a
    # refused run leaves every L2/L3 file and the manifest untouched.

    doc_dir.mkdir(parents=True, exist_ok=True)
    for stale in doc_dir.glob("*.md"):
        # Full ingest (or --sections with nothing to merge into): replace
        # everything. --sections onto an existing doc: only the files of
        # the chapters being rewritten go (matched by resolved stem, never
        # by prefix); the rest is someone's reviewed work and stays
        # byte-for-byte (this loop only ever touches *.md files here —
        # assets/ is handled, and already rebuilt, upstream in parser.py).
        if previous is None or _stem_of(stale.name) in resolved_old_stems:
            stale.unlink()

    groups: dict[str, list[SectionUnit]] = {}
    for unit in units:
        groups.setdefault(unit.chapter, []).append(unit)

    sections: list[models.SectionEntry] = []
    sections_by_chapter: dict[str, list[models.SectionEntry]] = {}
    files: list[str] = []
    for chapter, chapter_units in groups.items():
        head = next((u for u in chapter_units if u.id == chapter), chapter_units[0])
        stem_title = (part_titles or {}).get(chapter) or head.title
        stem = chapter_stem(chapter, stem_title)

        raw_path = doc_dir / f"{stem}.raw.md"
        l2_path = doc_dir / f"{stem}.md"
        if not (
            raw_path.resolve().is_relative_to(doc_dir.resolve())
            and l2_path.resolve().is_relative_to(doc_dir.resolve())
        ):
            # Defense-in-depth: validate_unit_ids() above already rejects a
            # path separator or '..' segment in any unit id, so this should
            # be unreachable — but a stem is derived from the id via
            # chapter_stem(), and this is the last point before a write.
            raise ValueError(
                f"chapter {chapter!r} resolves to a path outside the "
                f"document directory ({raw_path}) — refusing to write"
            )

        l3_lines: list[str] = []
        l2_lines: list[str] = []
        chapter_sections: list[models.SectionEntry] = []
        for unit in chapter_units:
            heading = f"## {unit.id} {unit.title}".rstrip()
            l3_lines += [heading, "", unit.body_md, ""]
            l2_lines += [
                heading,
                "",
                f"<!-- TODO:summarize {unit.id} -->",
                "",
            ]
            for table in unit.tables:
                l2_lines += [table, ""]
            for desc in extract_image_descs(unit.body_md):
                l2_lines += [f"Figure: {desc}", ""]
            entry = models.SectionEntry(
                id=unit.id,
                title=unit.title,
                file=stem,
                tokens=models.SectionTokens(l3=count_tokens(unit.body_md)),
            )
            sections.append(entry)
            chapter_sections.append(entry)
        sections_by_chapter[chapter] = chapter_sections

        raw_path.write_text("\n".join(l3_lines), encoding="utf-8", newline="\n")
        l2_path.write_text("\n".join(l2_lines), encoding="utf-8", newline="\n")
        files += [f"{stem}.md", f"{stem}.raw.md"]

    sha = (
        hashlib.sha256(source_path.read_bytes()).hexdigest()
        if source_path and source_path.exists()
        else ""
    )
    cfg = heading_config or HeadingConfig()
    manifest = models.Manifest(
        id=doc_id,
        title=title,
        revision=revision,
        ingested=date.today(),
        source_sha256=sha,
        sections=(
            _merge_sections(previous.sections, sections_by_chapter, stems)
            if previous is not None
            else sections
        ),
        ingest=models.IngestConfig(
            chapter_pattern=cfg.chapter_pattern,
            appendix_pattern=cfg.appendix_pattern,
            attachment_pattern=cfg.attachment_pattern,
            used_bookmarks=used_bookmarks,
        ),
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", manifest)

    index_path = kb_dir / "index.yaml"
    index = (
        models.load_yaml_model(index_path, models.KBIndex)
        if index_path.exists()
        else models.KBIndex()
    )
    kept = [d for d in index.docs if d.id != doc_id]
    entry = models.IndexEntry(id=doc_id, title=title, revision=revision, tags=tags)
    models.save_yaml_model(index_path, models.KBIndex(docs=kept + [entry]))

    return ScaffoldReport(
        doc_id=doc_id,
        files=files,
        n_sections=len(sections),
        token_stats=token_stats(sections),
    )
