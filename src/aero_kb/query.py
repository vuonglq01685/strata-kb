from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from rank_bm25 import BM25Plus

from aero_kb import models
from aero_kb.mdutils import count_tokens, slice_section


@dataclass
class QueryResult:
    doc_id: str
    section_id: str
    title: str
    score: float
    citation: str
    content: str
    tokens: int


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _citation(doc: models.IndexEntry | models.Manifest, section_id: str) -> str:
    base = f"{doc.id} §{section_id}"
    return f"{base} ({doc.revision})" if doc.revision else base


def search(
    kb_dir: Path,
    text: str,
    tags: list[str] | None = None,
    budget: int = 2000,
) -> list[QueryResult]:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return []
    index = models.load_yaml_model(index_path, models.KBIndex)

    docs = index.docs
    if tags:
        tagset = {t.strip().lower() for t in tags}
        docs = [
            d for d in index.docs
            if tagset & {t.lower() for t in d.tags} or d.id.lower() in tagset
        ]
        if not docs:
            return []

    corpus: list[tuple[models.IndexEntry, models.SectionEntry]] = []
    for doc in docs:
        manifest_path = kb_dir / doc.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for sec in manifest.sections:
            corpus.append((doc, sec))
    if not corpus:
        return []

    bm25 = BM25Plus([_tokenize(f"{s.title} {s.summary}") for _, s in corpus])
    scores = bm25.get_scores(_tokenize(text))
    ranked = sorted(zip(corpus, scores), key=lambda pair: -pair[1])

    results: list[QueryResult] = []
    used = 0
    for (doc, sec), score in ranked:
        if score <= 0:
            break
        l2_path = kb_dir / doc.id / f"{sec.file}.md"
        if not l2_path.exists():
            continue
        content = slice_section(l2_path.read_text(encoding="utf-8"), sec.id)
        if content is None:
            continue
        n_tokens = count_tokens(content)
        if results and used + n_tokens > budget:
            break
        results.append(
            QueryResult(
                doc_id=doc.id,
                section_id=sec.id,
                title=sec.title,
                score=float(score),
                citation=_citation(doc, sec.id),
                content=content,
                tokens=n_tokens,
            )
        )
        used += n_tokens
        if used >= budget:
            break
    return results


def get_section(
    kb_dir: Path, doc_id: str, section_id: str, level: str = "l2"
) -> QueryResult | None:
    section_id = section_id.lstrip("§")
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
    )
