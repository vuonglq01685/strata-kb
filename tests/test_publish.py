import pytest

from center_kb import federation, gitio, models
from center_kb import hub as hub_mod
from center_kb.publish import PublishError, PublishReport, publish


@pytest.fixture
def hub_bare(tmp_path, hub_worktree, run_git):
    """Hub bare origin seeded with hub_worktree content."""
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    return bare


def test_publish_to_hub_bare(monkeypatch, tmp_path, git_kb, hub_bare, run_git):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    report = publish(git_kb["kb"], str(hub_bare))
    assert isinstance(report, PublishReport)
    assert report.n_docs == 1
    assert report.pushed is True
    check = tmp_path / "check"
    gitio.clone(str(hub_bare), check)
    entry = check / "federation" / report.repo_id
    assert (entry / "index.yaml").exists()
    assert (entry / "manifests" / "demo-doc.yaml").exists()
    meta = models.load_yaml_model(entry / "_meta.yaml", federation.FederationMeta)
    assert meta.source_commit == gitio.head_commit(git_kb["root"])


def test_publish_direct_path_no_push(git_kb, hub_worktree):
    # hub is a worktree path with no remote → commit only, pushed=False
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="repo-a")
    assert report.pushed is False
    assert (hub_worktree / "federation" / "repo-a" / "_meta.yaml").exists()


def test_repo_id_collides_with_domain_doc(git_kb, hub_worktree):
    with pytest.raises(PublishError, match="arinc-424"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="arinc-424")


def test_push_race_retries_with_rebase(
    monkeypatch, tmp_path, git_kb, hub_bare, run_git, hub_worktree
):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")  # creates the clone cache
    # hub_worktree syncs the just-published commit (cache already pushed) before
    # creating the race commit — otherwise pushing race.txt below would be
    # rejected by bare due to non-fast-forward (hub_worktree and cache both
    # branch off from "hub v1").
    run_git(hub_worktree, "pull", "--ff-only", "origin", "HEAD")
    # origin advances after the cache is already fresh (default TTL 900s → 2nd time doesn't pull)
    (hub_worktree / "race.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "race")
    run_git(hub_worktree, "push", "origin", "HEAD")
    # change .kb so the 2nd publish has a diff → first push rejected → rebase → OK
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Updated summary for race test."
    models.save_yaml_model(manifest_path, manifest)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "update summary")
    report = publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")
    assert report.pushed is True
    check = tmp_path / "check2"
    gitio.clone(str(hub_bare), check)
    assert (check / "race.txt").exists()  # rebase keeps the upstream commit
    text = (check / "federation" / "repo-a" / "manifests" / "demo-doc.yaml").read_text(
        encoding="utf-8"
    )
    assert "Updated summary" in text


def test_unreachable_hub_raises(tmp_path, git_kb, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "does-not-exist.git"))


def test_cli_publish(git_kb, hub_worktree, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app

    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(
        app, ["publish", "--hub", str(hub_worktree), "--repo-id", "repo-a"]
    )
    assert result.exit_code == 0, result.output
    assert "repo-a" in result.output


def test_cli_publish_error_exit_1(git_kb, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from center_kb.cli import app

    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(app, ["publish", "--hub", str(tmp_path / "x.git")])
    assert result.exit_code == 1


# --- F1: sanitize repo_id before rmtree (path traversal) ---


def test_publish_repo_id_path_traversal_rejected(git_kb, hub_worktree):
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="../evil")
    # no filesystem side effects: no directory is created/deleted
    # outside hub_worktree's legitimate federation/
    assert not (hub_worktree.parent / "evil").exists()
    assert not (hub_worktree / "federation" / "evil").exists()


def test_publish_repo_id_dotdot_rejected(git_kb, hub_worktree):
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="..")
    # hub_worktree itself is still intact (not accidentally rmtree'd as the hub root)
    assert (hub_worktree / ".kb" / "index.yaml").exists()
    assert (hub_worktree / "federation").is_dir()


def test_publish_repo_id_traversal_no_filesystem_effect(git_kb, hub_worktree):
    before = sorted(p.name for p in hub_worktree.iterdir())
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(hub_worktree), repo_id="../../evil")
    after = sorted(p.name for p in hub_worktree.iterdir())
    assert before == after


# --- F2: publish only stages federation/ (doesn't push .kb-work/embeddings.db garbage) ---


def test_publish_excludes_kb_work_garbage_from_hub(monkeypatch, tmp_path, git_kb, hub_bare):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    # resolve_hub first to get handle.root (clone cache), then litter the cache
    # with embeddings.db — simulating `kb build` having run on the hub worktree.
    handle = hub_mod.resolve_hub(str(hub_bare))
    assert handle is not None
    (handle.root / ".kb-work").mkdir()
    (handle.root / ".kb-work" / "embeddings.db").write_text("garbage", encoding="utf-8")

    report = publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")
    assert report.pushed is True

    check = tmp_path / "check"
    gitio.clone(str(hub_bare), check)
    assert not (check / ".kb-work").exists()
    assert (check / "federation" / "repo-a" / "index.yaml").exists()
    # the garbage file is still there locally (untracked) — just not pushed to the hub
    assert (handle.root / ".kb-work" / "embeddings.db").exists()
