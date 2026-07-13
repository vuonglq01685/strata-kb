from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from rank_bm25 import BM25Plus

from center_kb import models
from center_kb.embed import SEMANTIC_FALLBACK_THRESHOLD
from center_kb.mdutils import count_tokens, slice_section

if TYPE_CHECKING:
    from center_kb.hub import HubHandle

logger = logging.getLogger("center_kb.query")


class AmbiguousDocError(LookupError):
    """doc_id tồn tại ở nhiều repo trong federation — cần qualify repo:doc."""

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
    match_mode: str = "keyword"  # "keyword" | "semantic"


@dataclass
class _Candidate:
    doc: models.IndexEntry
    sec: models.SectionEntry
    kb_dir: Path  # federation/<repo-id>/ (mirror .kb)
    source: str  # repo-id
    citation: str


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(
    repo_id: str, doc: models.IndexEntry | models.Manifest, section_id: str
) -> str:
    base = f"{repo_id}:{doc.id} §{section_id}"
    return f"{base} ({doc.revision})" if doc.revision else base


def _filter_tags(
    docs: list[models.IndexEntry], tags: list[str] | None
) -> list[models.IndexEntry]:
    if not tags:
        return docs
    tagset = {t.strip().lower() for t in tags}
    return [
        d for d in docs
        if tagset & {t.lower() for t in d.tags} or d.id.lower() in tagset
    ]


def _repo_candidates(
    repo_kb: Path, repo_id: str, tags: list[str] | None
) -> list[_Candidate]:
    index_path = repo_kb / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)
    out: list[_Candidate] = []
    for doc in _filter_tags(index.docs, tags):
        manifest_path = repo_kb / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            out.append(
                _Candidate(
                    doc=doc, sec=sec, kb_dir=repo_kb, source=repo_id,
                    citation=_citation(repo_id, doc, sec.id),
                )
            )
    return out


def _gather_candidates(hub: "HubHandle", tags: list[str] | None) -> list[_Candidate]:
    from center_kb.federation import load_federation

    out: list[_Candidate] = []
    for repo in load_federation(hub.federation_dir):
        out += _repo_candidates(repo.kb_dir, repo.meta.repo_id, tags)
    return out


def _candidate_content(c: _Candidate) -> str | None:
    l2_path = c.kb_dir / c.doc.id / f"{c.sec.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), c.sec.id)


def search(
    hub: "HubHandle",
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    semantic: bool = False,
    embedder=None,  # center_kb.embed.Embedder | None — injectable cho test
) -> list[QueryResult]:
    corpus = _gather_candidates(hub, tags)
    if not corpus:
        return []

    section_tokens = [tokenize(f"{c.sec.title} {c.sec.summary}") for c in corpus]
    bm25 = BM25Plus(section_tokens)
    query_token_list = tokenize(text)
    query_tokens = set(query_token_list)
    scores = bm25.get_scores(query_token_list)
    ranked = sorted(
        zip(corpus, section_tokens, scores), key=lambda triple: -triple[2]
    )

    results: list[QueryResult] = []
    used = 0
    for c, tokens, score in ranked:
        if score <= 0:
            break
        if not query_tokens & set(tokens):
            # BM25Plus cộng baseline idf*delta cho mọi term trong vocab —
            # section không chung token nào với query vẫn có thể score > 0.
            continue
        content = _candidate_content(c)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=c.doc.id,
                section_id=c.sec.id,
                title=c.sec.title,
                score=float(score),
                citation=c.citation,
                content=content,
                tokens=n_tokens,
                source=c.source,
            )
        )
        used += n_tokens
        if used >= budget:
            break

    top_score = results[0].score if results else 0.0
    if semantic or not results or top_score < SEMANTIC_FALLBACK_THRESHOLD:
        semantic_results = _semantic_fallback(hub, corpus, text, budget, embedder)
        if semantic_results:
            return semantic_results
    return results


def _semantic_fallback(
    hub: "HubHandle",
    corpus: list[_Candidate],
    text: str,
    budget: int,
    embedder,
) -> list[QueryResult]:
    """Routing bước 3: KNN sqlite-vec trên từng repo trong federation."""
    from center_kb import embed as embed_mod
    from center_kb.federation import load_federation

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if embedder is None:
        return []
    by_key = {(c.source, c.doc.id, c.sec.id): c for c in corpus}
    hits: list[tuple[str, str, str, float]] = []  # rid, doc, sec, score
    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        db_path = hub.root / ".kb-work" / f"embeddings-{rid}.db"
        try:
            embed_mod.ensure_index(repo.kb_dir, db_path, embedder)
            for doc_id, sec_id, score in embed_mod.semantic_search(
                db_path, embedder, text
            ):
                hits.append((rid, doc_id, sec_id, score))
        except Exception as exc:  # embedding best-effort — không được phá query
            logger.warning("semantic search error (%s) — skipping: %s", rid, exc)
    results: list[QueryResult] = []
    used = 0
    for rid, doc_id, sec_id, score in sorted(hits, key=lambda h: -h[3]):
        c = by_key.get((rid, doc_id, sec_id))
        if c is None:
            continue
        content = _candidate_content(c)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=doc_id, section_id=sec_id, title=c.sec.title,
                score=float(score), citation=c.citation, content=content,
                tokens=n_tokens, source=rid, match_mode="semantic",
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _get_section_in(
    repo_kb: Path, repo_id: str, doc_id: str, section_id: str, level: str
) -> QueryResult | None:
    manifest_path = repo_kb / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
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
        citation=_citation(repo_id, manifest, section_id),
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
