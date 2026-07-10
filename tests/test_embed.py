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


def test_semantic_search_filters_below_min_score(fixture_kb, tmp_path):
    # query rác không khớp trục nào → vec [0,0,0,0.1], distance 1.0 tới mọi
    # section (score 0.5) < SEMANTIC_MIN_SCORE (0.6) → không trả kết quả nào
    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    hits = embed.semantic_search(db, fake, "zzz qqq xxx")
    assert hits == []


class _BadDimEmbedder:
    """Embedder lỗi cấu hình: khai dim=4 nhưng trả vector 3 chiều."""

    dim = 4

    def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


def test_ensure_index_raises_on_wrong_vector_dim(fixture_kb, tmp_path):
    db = tmp_path / "emb.db"
    with pytest.raises(ValueError):
        embed.ensure_index(fixture_kb, db, _BadDimEmbedder())


def test_ensure_index_removes_deleted_section(fixture_kb, tmp_path):
    from aero_kb import models

    db = tmp_path / "emb.db"
    fake = FakeEmbedder()
    embed.ensure_index(fixture_kb, db, fake)
    manifest_path = fixture_kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections = [s for s in manifest.sections if s.id != "1.2"]
    models.save_yaml_model(manifest_path, manifest)
    embed.ensure_index(fixture_kb, db, fake)
    hits = embed.semantic_search(db, fake, "airway route identifiers")
    assert all(sec_id != "1.2" for _, sec_id, _ in hits)


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
