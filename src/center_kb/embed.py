from __future__ import annotations

import hashlib
import logging
import sqlite3
import struct
from pathlib import Path
from typing import Protocol

from center_kb import models
from center_kb.mdutils import slice_section

logger = logging.getLogger("center_kb.embed")

# BM25 top-score threshold that triggers step 3 (embedding fallback) — a
# neutral constant, to be tuned once measured on a real KB (spec Phase 3 §7).
SEMANTIC_FALLBACK_THRESHOLD = 5.0

SEMANTIC_MIN_SCORE = 0.6  # score floor 1/(1+distance) — filters out nearest-but-irrelevant results; tune once measured for real

_L2_HEAD_CHARS = 500  # leading chunk of L2 fed into the embedding text


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _FastEmbedder:
    """fastembed ONNX — bge-small-en-v1.5, 384 dimensions, fully local."""

    dim = 384

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


def default_embedder() -> Embedder | None:
    """Real embedder if [embed] is installed; None (with a log) if missing."""
    try:
        return _FastEmbedder()
    except ImportError:
        logger.info(
            "fastembed not installed — semantic search disabled, using BM25 "
            '(enable with: pip install "center-kb[embed]")'
        )
        return None
    except Exception as exc:  # model download failed (first run offline...)
        logger.warning("could not initialize embedder — falling back to BM25: %s", exc)
        return None


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _connect(db_path: Path, dim: int) -> sqlite3.Connection:
    import sqlite_vec

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sections(
            id INTEGER PRIMARY KEY,
            doc_id TEXT NOT NULL,
            section_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            UNIQUE(doc_id, section_id)
        )"""
    )
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_sections "
        f"USING vec0(embedding float[{dim}])"
    )
    return conn


def _section_text(kb_dir: Path, doc_id: str, sec: models.SectionEntry) -> str:
    text = f"{sec.title}\n{sec.summary}"
    l2_path = kb_dir / doc_id / f"{sec.file}.md"
    if l2_path.exists():
        content = slice_section(l2_path.read_text(encoding="utf-8"), sec.id)
        if content:
            text += "\n" + content[:_L2_HEAD_CHARS]
    return text


def ensure_index(kb_dir: Path, db_path: Path, embedder: Embedder) -> int:
    """Incrementally build/refresh the index by content-hash. Returns the number of sections re-embedded."""
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        return 0
    index = models.load_yaml_model(index_path, models.KBIndex)
    conn = _connect(db_path, embedder.dim)
    try:
        stored = {
            (row[1], row[2]): (row[0], row[3])
            for row in conn.execute(
                "SELECT id, doc_id, section_id, content_hash FROM sections"
            )
        }
        seen: set[tuple[str, str]] = set()
        to_embed: list[tuple[str, str, str, str]] = []  # doc, sec, hash, text
        for doc in index.docs:
            manifest_path = kb_dir / doc.id / "_manifest.yaml"
            if not manifest_path.exists():
                continue
            manifest = models.load_yaml_model(manifest_path, models.Manifest)
            for sec in manifest.sections:
                key = (doc.id, sec.id)
                seen.add(key)
                text = _section_text(kb_dir, doc.id, sec)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if key in stored and stored[key][1] == digest:
                    continue
                to_embed.append((doc.id, sec.id, digest, text))
        # delete sections that no longer exist
        for key, (rowid, _) in stored.items():
            if key not in seen:
                conn.execute("DELETE FROM sections WHERE id = ?", (rowid,))
                conn.execute("DELETE FROM vec_sections WHERE rowid = ?", (rowid,))
        if to_embed:
            vectors = embedder.embed([t[3] for t in to_embed])
            for vec in vectors:
                if len(vec) != embedder.dim:
                    raise ValueError(
                        f"embedder returned a {len(vec)}-dim vector, expected {embedder.dim} "
                        "dims (embedder.dim) — check the embedder configuration"
                    )
            for (doc_id, sec_id, digest, _), vec in zip(to_embed, vectors):
                old = stored.get((doc_id, sec_id))
                if old is not None:
                    conn.execute("DELETE FROM sections WHERE id = ?", (old[0],))
                    conn.execute(
                        "DELETE FROM vec_sections WHERE rowid = ?", (old[0],)
                    )
                cur = conn.execute(
                    "INSERT INTO sections(doc_id, section_id, content_hash) "
                    "VALUES (?, ?, ?)",
                    (doc_id, sec_id, digest),
                )
                conn.execute(
                    "INSERT INTO vec_sections(rowid, embedding) VALUES (?, ?)",
                    (cur.lastrowid, _serialize(vec)),
                )
        conn.commit()
        return len(to_embed)
    finally:
        conn.close()


def semantic_search(
    db_path: Path, embedder: Embedder, text: str, k: int = 10
) -> list[tuple[str, str, float]]:
    """KNN over the index — returns (doc_id, section_id, score) in descending score order."""
    if not db_path.exists():
        return []
    query_vec = embedder.embed([text])[0]
    conn = _connect(db_path, embedder.dim)
    try:
        rows = conn.execute(
            "SELECT s.doc_id, s.section_id, v.distance "
            "FROM vec_sections v JOIN sections s ON s.id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (_serialize(query_vec), k),
        ).fetchall()
    finally:
        conn.close()
    return [
        (doc, sec, 1.0 / (1.0 + dist))
        for doc, sec, dist in rows
        if 1.0 / (1.0 + dist) >= SEMANTIC_MIN_SCORE
    ]
