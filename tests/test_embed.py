import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from center_kb import embed


def _reset_cache():
    if hasattr(embed, "_reset_default_cache"):
        embed._reset_default_cache()


@pytest.mark.real_embedder
def test_default_embedder_none_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastembed"):
            raise ImportError("no fastembed")
        return real_import(name, *args, **kwargs)

    _reset_cache()
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert embed.default_embedder() is None
    _reset_cache()  # không để None cached rò sang test khác


@pytest.mark.real_embedder
def test_default_embedder_cached_per_process(monkeypatch):
    # MCP/web server gọi search() mỗi request — không được init lại
    # ONNX model (hàng trăm ms tới vài giây) mỗi lần
    inits = {"n": 0}

    class CountingEmbedder:
        dim = 4
        name = "counting"

        def __init__(self) -> None:
            inits["n"] += 1

        def embed(self, texts):
            return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(embed, "_FastEmbedder", CountingEmbedder)
    _reset_cache()
    try:
        first = embed.default_embedder()
        second = embed.default_embedder()
    finally:
        _reset_cache()  # không rò CountingEmbedder cached sang test khác
    assert first is second
    assert inits["n"] == 1


@pytest.mark.real_embedder
def test_default_embedder_thread_safe_single_init(monkeypatch):
    # MCP/web server đa luồng — check-then-set không lock sẽ init ONNX model
    # nhiều lần (chậm + leak instance)
    import threading
    import time

    inits = []

    class SlowEmbedder:
        dim = 4
        name = "slow"

        def __init__(self) -> None:
            time.sleep(0.05)
            inits.append(1)

        def embed(self, texts):
            return [[0.0] * 4 for _ in texts]

    monkeypatch.setattr(embed, "_FastEmbedder", SlowEmbedder)
    _reset_cache()
    got = []
    try:
        threads = [
            threading.Thread(target=lambda: got.append(embed.default_embedder()))
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        _reset_cache()
    assert len(inits) == 1
    assert len({id(g) for g in got}) == 1
