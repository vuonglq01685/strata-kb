from __future__ import annotations

import logging
import struct
import threading
from typing import Protocol

logger = logging.getLogger("strata_kb.embed")

SEMANTIC_MIN_SCORE = 0.6  # score floor 1/(1+distance) — filters out nearest-but-irrelevant results; tune once measured for real

_L2_HEAD_CHARS = 500  # leading chunk of L2 fed into the embedding text


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class _FastEmbedder:
    """fastembed ONNX — bge-small-en-v1.5, 384 dimensions, fully local."""

    dim = 384
    name = "BAAI/bge-small-en-v1.5"

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=self.name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


_UNRESOLVED = object()  # sentinel — distinguishes "not resolved yet" from "resolved to None"
_default_cache: object = _UNRESOLVED
_default_lock = threading.Lock()


def _reset_default_cache() -> None:
    """Test use only."""
    global _default_cache
    _default_cache = _UNRESOLVED


def default_embedder() -> Embedder | None:
    """Real embedder if [embed] is installed; None (with a log) if missing.

    Cached per process — including a None result (model init failure, e.g.
    offline at start): the MCP/web server calls search() on every request and
    must not reload the ONNX model each time. Deliberate trade-off (KISS, no
    TTL): if the server starts offline, the semantic leg stays off until
    restart. The lock prevents double-initializing ONNX when a multi-threaded
    server takes concurrent requests."""
    global _default_cache
    if _default_cache is _UNRESOLVED:
        with _default_lock:
            if _default_cache is _UNRESOLVED:
                _default_cache = _resolve_default()
    return _default_cache  # type: ignore[return-value]


def _resolve_default() -> Embedder | None:
    try:
        return _FastEmbedder()
    except ImportError:
        logger.info(
            "fastembed not installed — semantic search disabled, keyword search only "
            '(enable with: pip install "strata-kb[embed]")'
        )
        return None
    except Exception as exc:  # noqa: BLE001 -- degrade to FTS-only: model download failed (first run offline...)
        logger.warning(
            "could not initialize embedder — keyword search only: %s", exc
        )
        return None


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)
