#!/usr/bin/env python3
"""Perf smoke for the hybrid search index — run manually, NOT a CI gate.

    python scripts/perf_search_smoke.py --sections 5000
    python scripts/perf_search_smoke.py --sections 100000 --repos 20

Targets (spec §2): keyword leg < 100ms, hybrid query < 300ms (warm).
"""
from __future__ import annotations

import argparse
import shutil
import statistics
import tempfile
import time
from pathlib import Path

from strata_kb import models, searchdb
from strata_kb.federation import FederationMeta
from strata_kb.hub import HubHandle
from strata_kb.query import search


class HashEmbedder:
    """Cheap deterministic embedder — tokens hashed into 64 dims, normalized."""

    dim = 64
    name = "hash-64"

    def embed(self, texts):
        out = []
        for t in texts:
            vec = [0.0] * self.dim
            for tok in t.lower().split():
                vec[hash(tok) % self.dim] += 1.0
            norm = sum(v * v for v in vec) ** 0.5 or 1.0
            out.append([v / norm for v in vec])
        return out


WORDS = [
    "airspace", "airway", "waypoint", "procedure", "runway", "approach",
    "departure", "navaid", "frequency", "altitude", "restriction", "sector",
]


def build_hub(root: Path, n_sections: int, n_repos: int) -> None:
    fed = root / "federation"
    per_repo = max(1, n_sections // n_repos)
    for r in range(n_repos):
        rid = f"repo-{r:03d}"
        doc_id = f"doc-{r:03d}"
        doc_dir = fed / rid / doc_id
        doc_dir.mkdir(parents=True)
        sections, lines = [], []
        for s in range(per_repo):
            sid = f"{s // 100 + 1}.{s % 100 + 1}"
            w = [WORDS[(s + i + r) % len(WORDS)] for i in range(4)]
            title = f"{w[0].title()} {w[1].title()} Records {sid}"
            lines.append(
                f"## {sid} {title}\n\nCondensed {' '.join(w)} content row {s}.\n"
            )
            sections.append(
                models.SectionEntry(
                    id=sid, title=title,
                    summary=f"{' '.join(w)} structure fields.",
                    status="summarized", file="body",
                )
            )
        # newline-exempt: manual perf smoke, root is always tempfile.mkdtemp()
        # scratch (see main()), never committed.
        (doc_dir / "body.md").write_text("\n".join(lines), encoding="utf-8")
        models.save_yaml_model(
            doc_dir / "_manifest.yaml",
            models.Manifest(id=doc_id, title=doc_id, sections=sections),
        )
        models.save_yaml_model(
            fed / rid / "index.yaml",
            models.KBIndex(
                docs=[
                    models.IndexEntry(id=doc_id, title=doc_id, tags=[f"tag{r % 5}"])
                ]
            ),
        )
        models.save_yaml_model(
            fed / rid / "_meta.yaml",
            FederationMeta(
                repo_id=rid, source_commit="perf",
                published_at="2026-07-14T00:00:00+00:00",
            ),
        )
    (root / ".kb").mkdir()


def timed_ms(fn, n: int = 5) -> float:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return statistics.median(times)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sections", type=int, default=5000)
    ap.add_argument("--repos", type=int, default=10)
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="kb-perf-"))
    try:
        print(f"building synthetic hub: {args.sections} sections / {args.repos} repos")
        build_hub(tmp, args.sections, args.repos)
        hub = HubHandle(root=tmp)
        emb = HashEmbedder()
        t0 = time.perf_counter()
        report = searchdb.sync(hub, emb)
        print(
            f"sync cold:            {time.perf_counter() - t0:8.1f} s  "
            f"({report.sections_updated} sections, {report.embedded} embedded)"
        )
        print(f"sync warm (no-op):    {timed_ms(lambda: searchdb.sync(hub, emb)):8.1f} ms")
        conn = searchdb.open_fresh(hub, emb)
        q = "airspace restriction sector"
        print(f"fts leg warm:         {timed_ms(lambda: searchdb.fts_search(conn, q)):8.1f} ms")
        print(f"knn leg warm:         {timed_ms(lambda: searchdb.knn_search(conn, emb, q)):8.1f} ms")
        conn.close()
        print(f"search() hybrid warm: {timed_ms(lambda: search(hub, q, embedder=emb)):8.1f} ms")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
