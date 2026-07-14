from __future__ import annotations

import logging
import struct
from typing import Protocol

logger = logging.getLogger("center_kb.embed")

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


_UNRESOLVED = object()  # sentinel — phân biệt "chưa resolve" với "resolve ra None"
_default_cache: object = _UNRESOLVED


def _reset_default_cache() -> None:
    """Chỉ dùng trong test."""
    global _default_cache
    _default_cache = _UNRESOLVED


def default_embedder() -> Embedder | None:
    """Real embedder if [embed] is installed; None (with a log) if missing.

    Cached per process — kể cả kết quả None (model init fail): MCP/web server
    gọi search() mỗi request, không được load lại ONNX model mỗi lần."""
    global _default_cache
    if _default_cache is _UNRESOLVED:
        _default_cache = _resolve_default()
    return _default_cache  # type: ignore[return-value]


def _resolve_default() -> Embedder | None:
    try:
        return _FastEmbedder()
    except ImportError:
        logger.info(
            "fastembed not installed — semantic search disabled, keyword search only "
            '(enable with: pip install "center-kb[embed]")'
        )
        return None
    except Exception as exc:  # model download failed (first run offline...)
        logger.warning(
            "could not initialize embedder — keyword search only: %s", exc
        )
        return None


def _serialize(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)
