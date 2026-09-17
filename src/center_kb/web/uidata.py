# src/center_kb/web/uidata.py
"""Read-only aggregation for the web UI: Overview stats, rails, reader nav.

Everything derives from the hub federation mirror each request. Failures in
non-essential data (git metadata) degrade to empty values, never to a 500.
"""
from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from center_kb import gitio, models
from center_kb.federation import load_federation
from center_kb.hub import HubHandle
from center_kb.mdutils import count_tokens
from center_kb.models import Manifest, SectionEntry
from center_kb.review import MACHINE_SECTION_PREFIX

logger = logging.getLogger("center_kb.web.uidata")

_QUEUE_ORDER = {"pending": 0, "summarized": 1}


@dataclass(frozen=True)
class CatalogDoc:
    id: str
    repo: str
    title: str
    revision: str
    total: int
    reviewed: int
    summarized: int
    pending: int

    @property
    def done_pct(self) -> int:
        if not self.total:
            return 0
        return round(100 * (self.total - self.pending) / self.total)


@dataclass(frozen=True)
class QueueItem:
    repo: str
    doc_id: str
    section_id: str
    title: str
    status: str


@dataclass(frozen=True)
class StoreStats:
    docs: int
    sections: int
    repos: int
    l0_tokens: int


@dataclass(frozen=True)
class PublishInfo:
    commit: str = ""
    repos: list[str] = field(default_factory=list)
    published_at: str = ""


@dataclass(frozen=True)
class Coverage:
    total: int
    reviewed: int
    summarized: int
    pending: int


@dataclass(frozen=True)
class TreeNode:
    kind: str  # "chapter" | "section"
    label: str
    id: str = ""
    status: str = ""


@dataclass(frozen=True)
class TocEntry:
    anchor: str
    label: str


_HEADING_TAG_RE = re.compile(r"<h([1-6])>(.*?)</h\1>", re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _iter_manifests(hub: HubHandle) -> Iterator[tuple[str, Manifest]]:
    for repo in load_federation(hub.federation_dir):
        for doc in repo.index.docs:
            path = repo.kb_dir / doc.id / "_manifest.yaml"
            if not path.exists():
                continue
            try:
                yield repo.meta.repo_id, models.load_yaml_model(path, Manifest)
            except Exception as exc:  # noqa: BLE001 -- malformed manifest: skip, keep the page up
                logger.warning("skipping manifest %s: %s", path, exc)


def catalog(hub: HubHandle) -> list[CatalogDoc]:
    out: list[CatalogDoc] = []
    for repo_id, m in _iter_manifests(hub):
        counts = {"reviewed": 0, "summarized": 0, "pending": 0}
        total = 0
        for s in m.sections:
            # hist.* rows are machine-authored and never reviewed by design
            # (review.py, publish.unreviewed_sections) — counting them here
            # keeps a -svc doc's summarized/pending totals inflated forever.
            if s.id.startswith(MACHINE_SECTION_PREFIX):
                continue
            counts[s.status] += 1
            total += 1
        out.append(
            CatalogDoc(
                id=m.id, repo=repo_id, title=m.title, revision=m.revision,
                total=total, **counts,
            )
        )
    return out


def all_tags(hub: HubHandle) -> list[str]:
    tags = {
        t
        for repo in load_federation(hub.federation_dir)
        for doc in repo.index.docs
        for t in doc.tags
    }
    return sorted(tags)


def review_queue(hub: HubHandle, limit: int = 8) -> list[QueueItem]:
    items = [
        QueueItem(repo=repo_id, doc_id=m.id, section_id=s.id,
                  title=s.title, status=s.status)
        for repo_id, m in _iter_manifests(hub)
        for s in m.sections
        if s.status != "reviewed" and not s.id.startswith(MACHINE_SECTION_PREFIX)
    ]
    items.sort(key=lambda i: (_QUEUE_ORDER[i.status], i.doc_id, i.section_id))
    return items[:limit]


def store_stats(hub: HubHandle) -> StoreStats:
    repos = load_federation(hub.federation_dir)
    docs = 0
    sections = 0
    for _, m in _iter_manifests(hub):
        docs += 1
        sections += len(m.sections)
    index_path = hub.federation_dir / "index.yaml"
    l0 = count_tokens(index_path.read_text(encoding="utf-8")) if index_path.exists() else 0
    return StoreStats(docs=docs, sections=sections, repos=len(repos), l0_tokens=l0)


def last_publish(hub: HubHandle) -> PublishInfo:
    try:
        commit = gitio.head_commit(hub.root)[:7]
    except (gitio.GitError, OSError):
        commit = ""
    index_path = hub.federation_dir / "index.yaml"
    repos: list[str] = []
    published_at = ""
    if index_path.exists():
        try:
            fed = models.load_yaml_model(index_path, models.FederationIndex)
            repos = sorted({e.repo_id for e in fed.docs})
            published_at = max((e.published_at for e in fed.docs), default="")
        except Exception as exc:  # noqa: BLE001 -- best-effort: last-publish info stays empty on failure
            logger.warning("federation index unreadable: %s", exc)
    return PublishInfo(commit=commit, repos=repos, published_at=published_at)


def doc_coverage(manifest: Manifest) -> Coverage:
    counts = {"reviewed": 0, "summarized": 0, "pending": 0}
    total = 0
    for s in manifest.sections:
        if s.id.startswith(MACHINE_SECTION_PREFIX):
            continue
        counts[s.status] += 1
        total += 1
    return Coverage(total=total, **counts)


def section_tree(manifest: Manifest) -> list[TreeNode]:
    """Left-rail tree: section rows, with a chapter header row per source
    file — but only when the doc spans more than one file."""
    files = {s.file for s in manifest.sections}
    out: list[TreeNode] = []
    current: str | None = None
    for s in manifest.sections:
        if len(files) > 1 and s.file != current:
            current = s.file
            stem = s.file.rsplit(".", 1)[0]
            out.append(TreeNode(kind="chapter", label=stem.replace("-", " ")))
        out.append(TreeNode(kind="section", label=s.title, id=s.id, status=s.status))
    return out


def inject_heading_anchors(content_html: str) -> tuple[str, list[TocEntry]]:
    """Give every mdrender heading an id and return the matching TOC list.

    mdrender emits attribute-less <hN>escaped text</hN>, so a regex pass is
    safe here — this is not a general-purpose HTML rewriter.
    """
    toc: list[TocEntry] = []
    used: set[str] = set()

    def _sub(m: re.Match[str]) -> str:
        level, inner = m.group(1), m.group(2)
        label = html.unescape(_TAG_STRIP_RE.sub("", inner)).strip()
        slug = _SLUG_RE.sub("-", label.lower()).strip("-") or "section"
        anchor, n = slug, 2
        while anchor in used:
            anchor = f"{slug}-{n}"
            n += 1
        used.add(anchor)
        toc.append(TocEntry(anchor=anchor, label=label))
        return f'<h{level} id="{anchor}">{inner}</h{level}>'

    return _HEADING_TAG_RE.sub(_sub, content_html), toc


def prev_next(
    manifest: Manifest, section_id: str
) -> tuple[SectionEntry | None, SectionEntry | None]:
    ids = [s.id for s in manifest.sections]
    if section_id not in ids:
        return None, None
    i = ids.index(section_id)
    prev = manifest.sections[i - 1] if i > 0 else None
    nxt = manifest.sections[i + 1] if i < len(ids) - 1 else None
    return prev, nxt


def status_map(hub: HubHandle) -> dict[tuple[str, str, str], str]:
    return {
        (repo_id, m.id, s.id): s.status
        for repo_id, m in _iter_manifests(hub)
        for s in m.sections
    }
