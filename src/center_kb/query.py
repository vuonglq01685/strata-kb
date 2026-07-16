from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from center_kb import models
from center_kb.mdutils import count_tokens, slice_section, slice_subsection
from center_kb.searchdb import tokenize  # noqa: F401 — re-export (web/ui.py import)

if TYPE_CHECKING:
    from center_kb.hub import HubHandle
    from center_kb.searchdb import SectionRow

logger = logging.getLogger("center_kb.query")


class AmbiguousDocError(LookupError):
    """doc_id exists in several federation repos — must be qualified as repo:doc."""

    def __init__(self, doc_id: str, repo_ids: list[str]) -> None:
        self.doc_id = doc_id
        self.repo_ids = repo_ids
        options = ", ".join(f"{rid}:{doc_id}" for rid in repo_ids)
        super().__init__(
            f"doc '{doc_id}' exists in {len(repo_ids)} federation repos — "
            f"qualify the ref: {options}"
        )


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = ""  # repo-id trong federation
    match_mode: str = "keyword"  # "keyword" | "semantic" | "hybrid"
    snippet: str = ""  # trích L3 quanh match khi term không hiện trong L2


def _citation(repo_id: str, doc_id: str, revision: str, section_id: str) -> str:
    base = f"{repo_id}:{doc_id} §{section_id}"
    return f"{base} ({revision})" if revision else base


def _row_content(hub: "HubHandle", row: "SectionRow") -> str | None:
    l2_path = hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), row.section_id)


_SNIPPET_WINDOW = 150  # chars mỗi bên quanh hit đầu tiên trong L3


def _l3_snippet(
    hub: "HubHandle", row: "SectionRow", terms: list[str], content: str
) -> str:
    """Match nằm ở L3 (fold/tail) mà content L2 không chứa term nào → trích
    cửa sổ quanh hit đầu tiên để người dùng thấy vì sao section này khớp."""
    lower = content.lower()
    if not terms or any(t in lower for t in terms):
        return ""
    raw_path = (
        hub.federation_dir / row.repo_id / row.doc_id / f"{row.file}.raw.md"
    )
    if not raw_path.exists():
        return ""
    raw = slice_section(raw_path.read_text(encoding="utf-8"), row.section_id)
    if not raw:
        return ""
    raw_lower = raw.lower()
    for term in terms:
        pos = raw_lower.find(term)
        if pos < 0:
            continue
        start = max(0, pos - _SNIPPET_WINDOW)
        end = min(len(raw), pos + len(term) + _SNIPPET_WINDOW)
        prefix = "…" if start > 0 else ""
        suffix = "…" if end < len(raw) else ""
        return f"{prefix}{raw[start:end].strip()}{suffix}"
    return ""


def _search_index(
    hub: "HubHandle", embedder, text: str, tags: list[str] | None
) -> tuple[list[tuple[int, float, str]], dict[int, "SectionRow"]]:
    """Chạy 2 leg + RRF trên index. DB hỏng giữa chừng → xoá, rebuild đúng
    một lần; vẫn fail → raise (spec §5)."""
    from center_kb import searchdb

    for attempt in (1, 2):
        conn: sqlite3.Connection | None = None
        try:
            # open_fresh nằm TRONG try — corruption lộ ra lúc freshness sync
            # cũng phải được rebuild-once như corruption lúc query (spec §5)
            try:
                conn = searchdb.open_fresh(hub, embedder)
            except sqlite3.OperationalError as exc:
                if not searchdb.is_lock_error(exc):
                    raise
                # process khác đang giữ writer lock (sync dài) — phục vụ index
                # hiện có (stale) thay vì fail sau busy_timeout (spec §3.2)
                logger.warning("search.db busy — serving existing index: %s", exc)
                conn = searchdb.open_db(hub)
            fts_hits = searchdb.fts_search(conn, text, tags)
            knn_hits: list[tuple[int, float]] = []
            if embedder is not None:
                try:
                    knn_hits = searchdb.knn_search(conn, embedder, text, tags)
                except sqlite3.DatabaseError:
                    raise  # index hỏng — để nhánh rebuild xử lý
                except Exception as exc:  # embedding best-effort, không vỡ query
                    logger.warning("semantic leg failed — keyword only: %s", exc)
            fused = searchdb.rrf_merge(fts_hits, knn_hits)
            return fused, searchdb.load_sections(conn, [r for r, _, _ in fused])
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                conn.close()  # Windows: close trước khi unlink
                conn = None
            if attempt == 2 or searchdb.is_lock_error(exc):
                raise  # lock = process khác đang ghi — không phải corruption
            logger.warning("search.db corrupt — rebuilding once: %s", exc)
            searchdb.delete_db(hub)
        finally:
            if conn is not None:
                conn.close()
    raise AssertionError("unreachable")


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    embedder=None,  # center_kb.embed.Embedder | None — injectable cho test
) -> list[QueryResult]:
    from center_kb import embed as embed_mod

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if semantic and embedder is None:
        logger.warning(
            "semantic search requested but no embedder is available — "
            'keyword results only (enable with: pip install "center-kb[embed]")'
        )
    fused, rows = _search_index(hub, embedder, text, tags)
    terms = tokenize(text)

    results: list[QueryResult] = []
    used = 0
    for rowid, score, mode in fused:
        row = rows.get(rowid)
        if row is None:
            continue
        content = _row_content(hub, row)
        if content is None:
            continue
        snippet = "" if mode == "semantic" else _l3_snippet(hub, row, terms, content)
        n_tokens = count_tokens(content) + (count_tokens(snippet) if snippet else 0)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=row.doc_id,
                section_id=row.section_id,
                title=row.title,
                score=score,
                citation=_citation(
                    row.repo_id, row.doc_id, row.doc_revision, row.section_id
                ),
                content=content,
                tokens=n_tokens,
                source=row.repo_id,
                match_mode=mode,
                snippet=snippet,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _parent_entry(
    manifest: models.Manifest, section_id: str
) -> models.SectionEntry | None:
    """Folded id không có entry riêng — parent là entry có id là prefix dài
    nhất của id yêu cầu, cắt tại '.' hoặc '-' ('3.2.1' → '3.2';
    '5.6-commentary' → '5.6')."""
    best: models.SectionEntry | None = None
    for s in manifest.sections:
        if section_id.startswith((s.id + ".", s.id + "-")):
            if best is None or len(s.id) > len(best.id):
                best = s
    return best


def _folded_result(
    repo_kb: Path,
    repo_id: str,
    manifest: models.Manifest,
    doc_id: str,
    section_id: str,
    level: str,
) -> QueryResult | None:
    parent = _parent_entry(manifest, section_id)
    if parent is None:
        return None
    if level != "l3":
        # L2 không có anchor con (summary phủ cả folded child) — trả parent
        # với citation id parent, không nói dối vị trí.
        return _get_section_in(repo_kb, repo_id, doc_id, parent.id, level)
    path = repo_kb / doc_id / f"{parent.file}.raw.md"
    if not path.exists():
        return None
    parent_md = slice_section(path.read_text(encoding="utf-8"), parent.id)
    if parent_md is None:
        return None
    content = slice_subsection(parent_md, section_id)
    if content is None:
        return None
    head = content.splitlines()[0].split(None, 2)
    title = head[2] if len(head) == 3 else parent.title
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=count_tokens(content),
        source=repo_id,
    )


def _get_section_in(
    repo_kb: Path, repo_id: str, doc_id: str, section_id: str, level: str
) -> QueryResult | None:
    manifest_path = repo_kb / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return _folded_result(
            repo_kb, repo_id, manifest, doc_id, section_id, level
        )
    suffix = ".raw.md" if level == "l3" else ".md"
    path = repo_kb / doc_id / f"{sec.file}{suffix}"
    if not path.exists():
        return None
    content = slice_section(path.read_text(encoding="utf-8"), section_id)
    if content is None:
        return None
    return QueryResult(
        doc_id=doc_id,
        section_id=section_id,
        title=sec.title,
        score=0.0,
        citation=_citation(repo_id, manifest.id, manifest.revision, section_id),
        content=content,
        tokens=count_tokens(content),
        source=repo_id,
    )


def get_section(
    hub: "HubHandle",
    doc_id: str,
    section_id: str,
    level: str = "l2",
    repo: str | None = None,
) -> QueryResult | None:
    from center_kb.federation import load_federation

    section_id = section_id.lstrip("§")
    if ":" in doc_id and repo is None:
        repo, doc_id = doc_id.split(":", 1)
    holders = [
        r for r in load_federation(hub.federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc_id / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        raise AmbiguousDocError(doc_id, [r.meta.repo_id for r in holders])
    r = holders[0]
    return _get_section_in(r.kb_dir, r.meta.repo_id, doc_id, section_id, level)
