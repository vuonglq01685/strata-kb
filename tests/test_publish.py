import pytest

from aero_kb import federation, gitio, models
from aero_kb.publish import PublishError, PublishReport, publish


@pytest.fixture
def hub_bare(tmp_path, hub_worktree, run_git):
    """Hub bare origin đã seed nội dung hub_worktree."""
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")
    return bare


def test_publish_to_hub_bare(monkeypatch, tmp_path, git_kb, hub_bare, run_git):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
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
    # hub là worktree path không remote → commit tại chỗ, pushed=False
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="repo-a")
    assert report.pushed is False
    assert (hub_worktree / "federation" / "repo-a" / "_meta.yaml").exists()


def test_repo_id_collides_with_domain_doc(git_kb, hub_worktree):
    with pytest.raises(PublishError, match="arinc-424"):
        publish(git_kb["kb"], str(hub_worktree), repo_id="arinc-424")


def test_push_race_retries_with_rebase(
    monkeypatch, tmp_path, git_kb, hub_bare, run_git, hub_worktree
):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")  # tạo cache clone
    # hub_worktree đồng bộ commit vừa publish (cache đã push) trước khi tạo
    # commit race — nếu không, push race.txt bên dưới sẽ bị bare từ chối vì
    # non-fast-forward (hub_worktree và cache cùng phân nhánh từ "hub v1").
    run_git(hub_worktree, "pull", "--ff-only", "origin", "HEAD")
    # origin tiến lên sau khi cache đã tươi (TTL mặc định 900s → lần 2 không pull)
    (hub_worktree / "race.txt").write_text("x", encoding="utf-8")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "race")
    run_git(hub_worktree, "push", "origin", "HEAD")
    # đổi .kb để publish lần 2 có diff → push đầu reject → rebase → OK
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].summary = "Updated summary for race test."
    models.save_yaml_model(manifest_path, manifest)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "sua summary")
    report = publish(git_kb["kb"], str(hub_bare), repo_id="repo-a")
    assert report.pushed is True
    check = tmp_path / "check2"
    gitio.clone(str(hub_bare), check)
    assert (check / "race.txt").exists()  # rebase giữ commit upstream
    text = (check / "federation" / "repo-a" / "manifests" / "demo-doc.yaml").read_text(
        encoding="utf-8"
    )
    assert "Updated summary" in text


def test_unreachable_hub_raises(tmp_path, git_kb, monkeypatch):
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    with pytest.raises(PublishError):
        publish(git_kb["kb"], str(tmp_path / "khong-ton-tai.git"))


def test_cli_publish(git_kb, hub_worktree, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(
        app, ["publish", "--hub", str(hub_worktree), "--repo-id", "repo-a"]
    )
    assert result.exit_code == 0, result.output
    assert "repo-a" in result.output


def test_cli_publish_error_exit_1(git_kb, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(app, ["publish", "--hub", str(tmp_path / "x.git")])
    assert result.exit_code == 1
