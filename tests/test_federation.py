from pathlib import Path

from center_kb import federation, models


def _write_entry(fed_dir: Path, repo_id: str, doc_id: str) -> None:
    entry = fed_dir / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        federation.FederationMeta(
            repo_id=repo_id,
            source_url=f"git@host:{repo_id}.git",
            source_commit="abc1234",
            published_at="2026-07-10T00:00:00+00:00",
        ),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id=doc_id, title=doc_id, tags=["local"], summary=f"{doc_id} spec."
                )
            ]
        ),
    )
    models.save_yaml_model(
        entry / "manifests" / f"{doc_id}.yaml",
        models.Manifest(
            id=doc_id,
            title=doc_id,
            sections=[
                models.SectionEntry(
                    id="1.1",
                    title="Section One",
                    summary="Local mapping for domain records.",
                    status="reviewed",
                    file="ch1",
                )
            ],
        ),
    )


def test_load_two_repos(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "nav-data", "nav-mapping")
    _write_entry(fed, "crew-ops", "roster-sop")
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["crew-ops", "nav-data"]
    assert "roster-sop" in repos[0].manifests
    assert repos[0].manifests["roster-sop"].sections[0].id == "1.1"


def test_missing_dir_returns_empty(tmp_path):
    assert federation.load_federation(tmp_path / "missing-dir") == []


def test_broken_entry_skipped(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "ok-repo", "ok-doc")
    bad = fed / "bad-repo"
    bad.mkdir()
    (bad / "_meta.yaml").write_text("::::", encoding="utf-8")
    repos = federation.load_federation(fed)
    assert [r.meta.repo_id for r in repos] == ["ok-repo"]


def test_broken_manifest_skipped_entry_kept(tmp_path):
    fed = tmp_path / "federation"
    _write_entry(fed, "nav-data", "nav-mapping")
    (fed / "nav-data" / "manifests" / "broken.yaml").write_text("::::", encoding="utf-8")
    repos = federation.load_federation(fed)
    assert list(repos[0].manifests) == ["nav-mapping"]
