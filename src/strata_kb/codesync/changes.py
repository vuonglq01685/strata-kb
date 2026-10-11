"""Fact-level changes of `-code` / `-svc` hub docs between two commits (spec §5).

Reads git objects only (never the worktree). A section is `changed` only when
its `facts_for` set differs, so banner, Image, Source and formatting edits
yield nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

from strata_kb import gitio, mdutils, models
from strata_kb.codesync.facts import Fact, facts_for

_MANIFEST_RE = re.compile(
    r"federation/(?:.+/)?(?P<rid>[^/]+)/(?P<doc>[^/]+-(?P<kind>code|svc))/_manifest\.yaml"
)

_DocKey = tuple[str, str]  # (repo_id, doc_id)
# One doc at one sha: its title and {section id: (section title, facts)}.
_Doc = tuple[str, dict[str, tuple[str, frozenset[Fact]]]]


@dataclass(frozen=True)
class ChangedItem:
    repo_id: str
    doc_id: str
    section_id: str | None  # None = whole doc added/removed
    title: str  # section title; doc title when section_id is None
    status: Literal["added", "removed", "changed"]
    added: frozenset[Fact]
    removed: frozenset[Fact]


def _docs_at(root: Path, reader: gitio.BatchReader, sha: str) -> dict[_DocKey, _Doc]:
    out: dict[_DocKey, _Doc] = {}
    for path in gitio.ls_tree(root, sha, "federation"):
        m = _MANIFEST_RE.fullmatch(path)
        if m is None:
            continue
        text = reader.read_at(sha, root / path)
        if text is None:
            continue
        manifest = models.Manifest.model_validate(yaml.safe_load(text))
        kind: Literal["code", "svc"] = "code" if m["kind"] == "code" else "svc"
        folder = (root / path).parent
        occurrences = mdutils.heading_occurrences(manifest.sections)
        sections: dict[str, tuple[str, frozenset[Fact]]] = {}
        for sec, occ in zip(manifest.sections, occurrences, strict=True):
            l2 = _slice(reader, sha, folder / f"{sec.file}.md", sec.id, occ)
            l3 = _slice(reader, sha, folder / f"{sec.file}.raw.md", sec.id, occ)
            facts = facts_for(sec.id, kind, l2, l3)
            title, prior = sections.get(sec.id, (sec.title, frozenset()))
            sections[sec.id] = (title, prior | facts)
        out[(m["rid"], m["doc"])] = (manifest.title, sections)
    return out


def _slice(
    reader: gitio.BatchReader, sha: str, path: Path, sid: str, occurrence: int
) -> str:
    md = reader.read_at(sha, path)
    return (mdutils.slice_section(md, sid, occurrence) or "") if md else ""


def _whole(doc: _Doc) -> frozenset[Fact]:
    return frozenset().union(*(facts for _, facts in doc[1].values()))


def _doc_items(
    rid: str, did: str, old: _Doc | None, new: _Doc | None
) -> list[ChangedItem]:
    if new is None and old is not None:
        return [
            ChangedItem(rid, did, None, old[0], "removed", frozenset(), _whole(old))
        ]
    if old is None and new is not None:
        return [ChangedItem(rid, did, None, new[0], "added", _whole(new), frozenset())]
    if old is None or new is None:  # pragma: no cover - key came from one side
        return []
    items: list[ChangedItem] = []
    for sid in old[1].keys() | new[1].keys():
        o, n = old[1].get(sid), new[1].get(sid)
        of, nf = (o[1] if o else frozenset()), (n[1] if n else frozenset())
        status = "added" if o is None else "removed" if n is None else "changed"
        title = n[0] if n else o[0] if o else sid
        items.append(ChangedItem(rid, did, sid, title, status, nf - of, of - nf))
    return items


def code_changes(root: Path, base: str, head: str) -> list[ChangedItem]:
    """Items that differ between commits `base` and `head`, sorted by
    `(repo_id, doc_id, section_id or "")`. GitError if either is missing."""
    root = root.resolve()
    with gitio.BatchReader(root) as reader:
        before = _docs_at(root, reader, base)
        after = _docs_at(root, reader, head)
    items = [
        item
        for key in before.keys() | after.keys()
        for item in _doc_items(*key, before.get(key), after.get(key))
    ]
    return sorted(
        (i for i in items if i.added or i.removed),
        key=lambda i: (i.repo_id, i.doc_id, i.section_id or ""),
    )
