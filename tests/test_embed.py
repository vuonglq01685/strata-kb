import pytest

sqlite_vec = pytest.importorskip("sqlite_vec")

from aero_kb import embed


class FakeEmbedder:
    """Vector 4 chiều xác định trước theo từ khóa — không cần model thật."""

    dim = 4

    def embed(self, texts):
        out = []
        for t in texts:
            t = t.lower()
            out.append(
                [
                    1.0 if "airspace" in t else 0.0,
                    1.0 if "airway" in t else 0.0,
                    1.0 if "roster" in t else 0.0,
                    0.1,
                ]
            )
        return out


def test_ensure_index_builds_then_incremental(fixture_kb, tmp_path):
    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    n1 = embed.ensure_index(fixture_kb, db, fake)
    assert n1 == 2  # demo-doc có 2 section
    n2 = embed.ensure_index(fixture_kb, db, fake)
    assert n2 == 0  # không đổi → không re-embed


def test_ensure_index_reembeds_changed_section(fixture_kb, tmp_path):
    from aero_kb import models

    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Changed summary about airspace."
    models.save_yaml_model(manifest_path, manifest)
    assert embed.ensure_index(fixture_kb, db, fake) == 1


def test_semantic_search_ranks_by_similarity(fixture_kb, tmp_path):
    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    hits = embed.semantic_search(db, fake, "airspace designation rules")
    assert hits
    assert hits[0][0] == "demo-doc"
    assert hits[0][1] == "1.1"  # section airspace gần query hơn airway
    assert hits[0][2] > hits[-1][2] if len(hits) > 1 else True


def test_default_embedder_none_when_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("fastembed"):
            raise ImportError("no fastembed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert embed.default_embedder() is None


@pytest.mark.skipif(
    "not config.getoption('--run-slow', default=False)",
    reason="cần --run-slow (tải model ~100MB)",
)
def test_real_fastembed_roundtrip(fixture_kb, tmp_path):
    embedder = embed.default_embedder()
    if embedder is None:
        pytest.skip("fastembed chưa cài")
    db = tmp_path / "emb.db"
    embed.ensure_index(fixture_kb, db, embedder)
    hits = embed.semantic_search(db, embedder, "controlled airspace zones")
    assert hits and hits[0][0] == "demo-doc"
