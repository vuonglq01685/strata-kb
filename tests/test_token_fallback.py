"""2026-10-10 review §6.2 F4/F5: tiktoken downloads cl100k_base on first use
into a temp dir; offline or behind a proxy that raised a ProxyError
traceback out of every command that counts tokens."""

from __future__ import annotations

import logging

import pytest
import tiktoken

from strata_kb import mdutils


@pytest.fixture
def fresh_encoder(monkeypatch):
    monkeypatch.setattr(mdutils, "_ENCODER", None)
    monkeypatch.setattr(mdutils, "_ENCODER_FAILED", False)
    monkeypatch.delenv("TIKTOKEN_CACHE_DIR", raising=False)
    monkeypatch.delenv("DATA_GYM_CACHE_DIR", raising=False)
    monkeypatch.setenv("HOME", "/nonexistent-home")


def test_an_unloadable_encoding_falls_back_to_an_estimate_and_warns_once(
    fresh_encoder, monkeypatch, caplog
):
    def offline(name):
        raise OSError("Tunnel connection failed: 403 Forbidden")

    monkeypatch.setattr(tiktoken, "get_encoding", offline)
    with caplog.at_level(logging.WARNING, logger="strata_kb.mdutils"):
        assert mdutils.count_tokens("x" * 40) == 10
        assert mdutils.count_tokens("abcde") == 2
        assert mdutils.count_tokens("") == 0
    warnings = [r for r in caplog.records if "token counts are estimates" in r.message]
    assert len(warnings) == 1
    assert "403 Forbidden" in warnings[0].getMessage()


def test_the_stable_cache_dir_is_tried_first(fresh_encoder, monkeypatch):
    seen = []

    class Enc:
        def encode(self, text):
            return text.split()

    def loader(name):
        import os

        seen.append(os.environ.get("TIKTOKEN_CACHE_DIR"))
        return Enc()

    monkeypatch.setattr(tiktoken, "get_encoding", loader)
    assert mdutils.count_tokens("a b c") == 3
    assert seen == [str(mdutils.tiktoken_cache_dir())]
    assert seen[0].endswith(".strata-kb/tiktoken") or seen[0].endswith(
        ".strata-kb\\tiktoken"
    )


def test_the_temp_dir_cache_from_older_releases_is_still_used(
    fresh_encoder, monkeypatch
):
    """A machine that cached the file under tiktoken's default temp dir must
    not lose it offline because the default moved."""
    import os

    attempts = []

    class Enc:
        def encode(self, text):
            return [0]

    def loader(name):
        attempts.append(os.environ.get("TIKTOKEN_CACHE_DIR"))
        if os.environ.get("TIKTOKEN_CACHE_DIR"):
            raise OSError("not in the new cache, and offline")
        return Enc()

    monkeypatch.setattr(tiktoken, "get_encoding", loader)
    assert mdutils.count_tokens("anything") == 1
    assert attempts == [str(mdutils.tiktoken_cache_dir()), None]


def test_an_operator_cache_dir_is_respected(fresh_encoder, monkeypatch, tmp_path):
    import os

    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(tmp_path))
    seen = []

    class Enc:
        def encode(self, text):
            return [0, 0]

    monkeypatch.setattr(
        tiktoken,
        "get_encoding",
        lambda name: seen.append(os.environ["TIKTOKEN_CACHE_DIR"]) or Enc(),
    )
    assert mdutils.count_tokens("x") == 2
    assert seen == [str(tmp_path)]


def test_mdutils_does_not_import_tiktoken_at_import_time():
    import ast
    from pathlib import Path

    tree = ast.parse(Path(mdutils.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name for n in top for a in n.names} | {
        n.module for n in top if isinstance(n, ast.ImportFrom)
    }
    assert "tiktoken" not in names
