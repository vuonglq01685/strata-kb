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


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int
    source: str = "local"  # "local" | "hub" | "remote:<repo-id>"


@dataclass
class _Candidate:
    doc: models.IndexEntry
    sec: models.SectionEntry
    kb_dir: Path | None  # None = federation, no L2 to load
    source: str
    citation: str
    pointer: str = ""  # line pointing back to the source repo (remote only)


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(doc: models.IndexEntry | models.Manifest, section_id: str) -> str:
    base = f"{doc.id} §{section_id}"
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


def _local_candidates(
    kb_dir: Path, tags: list[str] | None, source: str = "local"
) -> list[_Candidate]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)
    out: list[_Candidate] = []
    for doc in _filter_tags(index.docs, tags):
        manifest_path = kb_dir / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            out.append(
                _Candidate(
                    doc=doc, sec=sec, kb_dir=kb_dir, source=source,
                    citation=_citation(doc, sec.id),
                )
            )
    return out


def _federation_candidates(
    hub: "HubHandle", tags: list[str] | None
) -> list[_Candidate]:
    from center_kb.federation import load_federation

    out: list[_Candidate] = []
    for repo in load_federation(hub.federation_dir):
        rid = repo.meta.repo_id
        for doc in _filter_tags(repo.index.docs, tags):
            manifest = repo.manifests.get(doc.id)
            if manifest is None:
                continue
            for sec in manifest.sections:
                base = f"{rid}:{doc.id} §{sec.id}"
                citation = f"{base} ({doc.revision})" if doc.revision else base
                pointer = (
                    f"[remote] repo '{rid}'"
                    + (f" ({repo.meta.source_url})" if repo.meta.source_url else "")
                    + " — L1 summary only; read the full content at the source repo."
                )
                out.append(
                    _Candidate(
                        doc=doc, sec=sec, kb_dir=None, source=f"remote:{rid}",
                        citation=citation, pointer=pointer,
                    )
                )
    return out


def _candidate_content(c: _Candidate) -> str | None:
    if c.kb_dir is None:
        return f"{c.sec.summary}\n\n{c.pointer}"
    l2_path = c.kb_dir / c.doc.id / f"{c.sec.file}.md"
    if not l2_path.exists():
        return None
    return slice_section(l2_path.read_text(encoding="utf-8"), c.sec.id)


def _gather_candidates(
    kb_dir: Path, tags: list[str] | None, hub: "HubHandle | None"
) -> list[_Candidate]:
    candidates = _local_candidates(kb_dir, tags)
    if hub is None:
        return candidates
    local_ids = {c.doc.id for c in candidates}
    # local wins on collision: read the full local index (unfiltered by tag) to block
    index_path = kb_dir / "index.yaml"
    if index_path.exists():
        local_ids |= {
            d.id for d in models.load_yaml_model(index_path, models.KBIndex).docs
        }
    hub_candidates = [
        c for c in _local_candidates(hub.kb_dir, tags, source="hub")
        if c.doc.id not in local_ids
    ]
    return candidates + hub_candidates + _federation_candidates(hub, tags)


def search(
    kb_dir: Path,
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
    hub: "HubHandle | None" = None,
    semantic: bool = False,
    embedder=None,  # center_kb.embed.Embedder | None — injectable for tests
) -> list[QueryResult]:
    corpus = _gather_candidates(kb_dir, tags, hub)
    if not corpus:
        return []

    section_tokens = [_tokenize(f"{c.sec.title} {c.sec.summary}") for c in corpus]
    bm25 = BM25Plus(section_tokens)
    query_token_list = _tokenize(text)
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
            # BM25Plus adds an idf*delta baseline to every in-vocabulary
            # query term, so sections sharing zero tokens with the query
            # can still score > 0. Skip them explicitly.
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
        semantic_results = _semantic_fallback(
            kb_dir, hub, corpus, text, budget, embedder
        )
        if semantic_results:
            return semantic_results
    return results


def _semantic_fallback(
    kb_dir: Path,
    hub: "HubHandle | None",
    corpus: list[_Candidate],
    text: str,
    budget: int,
    embedder,
) -> list[QueryResult]:
    """Routing step 3: KNN over sqlite-vec, local + hub only (have L2)."""
    from center_kb import embed as embed_mod

    if embedder is None:
        embedder = embed_mod.default_embedder()
    if embedder is None:
        return []
    by_key: dict[tuple[str, str, str], _Candidate] = {}
    for c in corpus:
        if c.kb_dir is not None:  # skip federation
            by_key[(c.source, c.doc.id, c.sec.id)] = c
    hits: list[tuple[str, str, str, float]] = []  # source, doc, sec, score
    stores: list[tuple[str, Path, Path]] = [
        ("local", kb_dir, kb_dir.resolve().parent / ".kb-work" / "embeddings.db")
    ]
    if hub is not None:
        stores.append(("hub", hub.kb_dir, hub.root / ".kb-work" / "embeddings.db"))
    for source, source_kb, db_path in stores:
        try:
            embed_mod.ensure_index(source_kb, db_path, embedder)
            for doc_id, sec_id, score in embed_mod.semantic_search(
                db_path, embedder, text
            ):
                hits.append((source, doc_id, sec_id, score))
        except Exception as exc:  # embedding is best-effort — must never break the query
            logger.warning("semantic search error (%s) — skipping: %s", source, exc)
    results: list[QueryResult] = []
    used = 0
    for source, doc_id, sec_id, score in sorted(hits, key=lambda h: -h[3]):
        c = by_key.get((source, doc_id, sec_id))
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
                tokens=n_tokens, source=c.source,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def _get_section_in(
    kb_dir: Path, doc_id: str, section_id: str, level: str, source: str
) -> QueryResult | None:
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return None
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    sec = next((s for s in manifest.sections if s.id == section_id), None)
    if sec is None:
        return None
    suffix = ".raw.md" if level == "l3" else ".md"
    path = kb_dir / doc_id / f"{sec.file}{suffix}"
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
        citation=_citation(manifest, section_id),
        content=content,
        tokens=count_tokens(content),
        source=source,
    )


def get_section(
    kb_dir: Path,
    doc_id: str,
    section_id: str,
    level: str = "l2",
    hub: "HubHandle | None" = None,
) -> QueryResult | None:
    section_id = section_id.lstrip("§")
    result = _get_section_in(kb_dir, doc_id, section_id, level, "local")
    if result is not None:
        return result
    if hub is not None and (hub.kb_dir / doc_id / "_manifest.yaml").exists():
        # local wins: only fall through to the hub when local has no such doc
        return _get_section_in(hub.kb_dir, doc_id, section_id, level, "hub")
    return None
