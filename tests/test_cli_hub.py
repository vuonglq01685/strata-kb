from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_query_reads_federation_only(fed_hub, fixture_kb):
    # fixture_kb holds demo-doc, which is NOT published — it must not show up
    result = runner.invoke(
        app,
        ["query", "restrictive airspace designation",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424 §5.3" in result.output
    assert "demo-doc" not in result.output


def test_query_without_hub_config_errors_with_guide(fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    result = runner.invoke(
        app, ["query", "anything", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 1
    assert "config.yaml" in result.output


def test_query_hub_from_config_file(fed_hub, fixture_kb, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    (fixture_kb / "config.yaml").write_text(f"hub: {fed_hub}\n", encoding="utf-8")
    result = runner.invoke(
        app, ["query", "restrictive airspace", "--kb-dir", str(fixture_kb)]
    )
    assert result.exit_code == 0
    assert "arinc-kb:arinc-424" in result.output


def test_get_with_repo_and_l3(fed_hub, fixture_kb):
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--level", "l3", "--repo", "arinc-kb",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0
    assert "Full raw restrictive airspace" in result.output


def test_get_ambiguous_doc_errors(fed_hub, fixture_kb):
    from tests.conftest import make_fed_entry

    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    result = runner.invoke(
        app,
        ["get", "arinc-424", "5.3", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "dup-kb:arinc-424" in result.output


def test_reindex_repairs_aggregate_index(git_kb, hub_worktree):
    from center_kb.publish import publish

    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    (hub_worktree / "federation" / "index.yaml").write_text(
        "docs: []\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["reindex", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    from center_kb import models

    idx = models.load_yaml_model(
        hub_worktree / "federation" / "index.yaml", models.FederationIndex
    )
    assert [(e.repo_id, e.doc_id) for e in idx.docs] == [("demo-kb", "demo-doc")]


def test_publish_cli_prints_pr_url(git_kb, hub_worktree, monkeypatch):
    from center_kb import publish as publish_mod

    def fake_publish(kb_dir, hub_ref, repo_id=None, mode="auto"):
        return publish_mod.PublishReport(
            repo_id="demo-kb", source_commit="abc1234", n_docs=1,
            pushed=True, mode="pr", pr_url="https://github.com/org/hub/pull/7",
        )

    monkeypatch.setattr(publish_mod, "publish", fake_publish)
    result = runner.invoke(
        app, ["publish", "--hub", str(hub_worktree), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert "pull/7" in result.output


def test_reindex_builds_search_db(fed_hub, git_kb):
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 0
    assert (fed_hub / ".kb-work" / "search.db").exists()
    assert "search index" in result.output


def test_reindex_commits_index_before_search_sync(fed_hub, git_kb, run_git, monkeypatch):
    # a sync (embed) blowup must still surface the error, but the rebuilt
    # federation/index.yaml must not sit uncommitted — commit first, sync after
    from center_kb import searchdb as searchdb_mod

    (fed_hub / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "corrupt index")

    def boom(handle, embedder):
        raise RuntimeError("embed exploded")

    monkeypatch.setattr(searchdb_mod, "sync", boom)
    result = runner.invoke(
        app, ["reindex", "--hub", str(fed_hub), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code != 0  # strict embed error — must surface
    assert run_git(fed_hub, "status", "--porcelain", "--", "federation") == ""


def test_cli_publish_hub_kind_dispatches_federation(tmp_path, run_git, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.conftest import make_fed_entry
    from tests.test_publish_hub import _git_repo

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8"
    )
    _git_repo(run_git, mid)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root_hub / "federation" / "mid" / "repo-a" / "index.yaml").exists()


def test_cli_publish_root_hub_without_upstream_errors(tmp_path, run_git):
    from typer.testing import CliRunner

    from center_kb.cli import app
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    _git_repo(run_git, root_hub)

    result = CliRunner().invoke(app, ["publish", "--kb-dir", str(root_hub / ".kb")])
    assert result.exit_code == 1
    assert "root hub" in result.output
