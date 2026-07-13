from center_kb import models
from center_kb.federation import (
    build_federation_index,
    load_federation,
    write_federation_index,
)
from tests.conftest import make_fed_entry


def test_load_federation_reads_mirror_entries(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "icao-kb", "icao-annex-2")
    make_fed_entry(fed, "arinc-kb", "arinc-424")
    repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["arinc-kb", "icao-kb"]
    assert repos[0].kb_dir == fed / "arinc-kb"
    assert repos[0].index.docs[0].id == "arinc-424"


def test_load_federation_missing_dir_returns_empty(tmp_path):
    assert load_federation(tmp_path / "nope") == []


def test_load_federation_skips_old_slim_layout(tmp_path, caplog):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "new-kb", "doc-a")
    old = fed / "old-kb"
    (old / "manifests").mkdir(parents=True)
    (old / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (old / "_meta.yaml").write_text(
        "repo_id: old-kb\nsource_commit: abc\n", encoding="utf-8"
    )
    with caplog.at_level("WARNING"):
        repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["new-kb"]
    assert "old slim layout" in caplog.text


def test_load_federation_skips_broken_entry(tmp_path, caplog):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "good-kb", "doc-a")
    bad = fed / "bad-kb"
    bad.mkdir(parents=True)
    (bad / "index.yaml").write_text("docs: []\n", encoding="utf-8")  # thiếu _meta.yaml
    with caplog.at_level("WARNING"):
        repos = load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["good-kb"]


def test_build_federation_index_deterministic_and_sorted(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "icao-kb", "icao-annex-2", tags=["icao"], source_commit="c1")
    make_fed_entry(fed, "arinc-kb", "arinc-424", tags=["arinc424"], source_commit="c2")
    idx1 = build_federation_index(fed)
    idx2 = build_federation_index(fed)
    assert idx1 == idx2
    assert [(e.repo_id, e.doc_id) for e in idx1.docs] == [
        ("arinc-kb", "arinc-424"),
        ("icao-kb", "icao-annex-2"),
    ]
    assert idx1.docs[0].source_commit == "c2"
    assert idx1.docs[0].tags == ["arinc424"]


def test_write_federation_index_saves_and_reloads(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "solo-kb", "doc-a")
    path = write_federation_index(fed)
    assert path == fed / "index.yaml"
    loaded = models.load_yaml_model(path, models.FederationIndex)
    assert loaded.docs[0].repo_id == "solo-kb"


def test_aggregate_index_file_not_treated_as_entry(tmp_path):
    fed = tmp_path / "federation"
    make_fed_entry(fed, "solo-kb", "doc-a")
    write_federation_index(fed)
    assert len(load_federation(fed)) == 1
