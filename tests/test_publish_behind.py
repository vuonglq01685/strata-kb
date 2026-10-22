"""Dev-repo publish refuses when behind origin/<default> (spec 7.8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import cli as cli_mod
from strata_kb import publish as publish_mod
from strata_kb.cli import app

runner = CliRunner()


def _with_origin(git_kb: dict, run_git, tmp_path: Path, kind: str) -> Path:
    """Give git_kb an origin it has pushed to; return a second clone of it."""
    root: Path = git_kb["root"]
    (git_kb["kb"] / "config.yaml").write_text(f"kind: {kind}\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "kind")
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(root, "remote", "add", "origin", str(origin))
    run_git(root, "push", "-u", "origin", "HEAD")
    other = tmp_path / "other"
    run_git(tmp_path, "clone", str(origin), str(other))
    return other


def _push_from(other: Path, run_git) -> None:
    (other / "newer.txt").write_text("a newer hist row\n", encoding="utf-8")
    run_git(other, "add", "-A")
    run_git(other, "commit", "-m", "newer row")
    run_git(other, "push", "origin", "HEAD")


def _branch(root: Path, run_git) -> str:
    return run_git(root, "rev-parse", "--abbrev-ref", "HEAD")


def _publish(git_kb: dict, hub: Path, monkeypatch):
    monkeypatch.setattr(cli_mod, "_refresh_dev_code", lambda kb_dir: None)
    return runner.invoke(
        app, ["publish", "--hub", str(hub), "--kb-dir", str(git_kb["kb"])]
    )


def test_dev_publish_refuses_when_behind(
    git_kb, hub_worktree, run_git, tmp_path, monkeypatch
):
    other = _with_origin(git_kb, run_git, tmp_path, "dev")
    _push_from(other, run_git)
    branch = _branch(git_kb["root"], run_git)

    with pytest.raises(publish_mod.PublishError) as exc:
        publish_mod.ensure_current(git_kb["root"])
    assert str(exc.value) == f"behind origin/{branch} — pull, then kb publish"

    result = _publish(git_kb, hub_worktree, monkeypatch)
    assert result.exit_code == 1
    assert f"behind origin/{branch} — pull, then kb publish" in result.output
    assert not (hub_worktree / "federation").exists() or not any(
        (hub_worktree / "federation").glob("*/_meta.yaml")
    )


def test_dev_publish_ok_when_current(
    git_kb, hub_worktree, run_git, tmp_path, monkeypatch
):
    other = _with_origin(git_kb, run_git, tmp_path, "dev")
    _push_from(other, run_git)
    run_git(git_kb["root"], "pull", "--ff-only")

    result = _publish(git_kb, hub_worktree, monkeypatch)
    assert result.exit_code == 0, result.output


def test_dev_publish_ok_when_ahead(
    git_kb, hub_worktree, run_git, tmp_path, monkeypatch
):
    _with_origin(git_kb, run_git, tmp_path, "dev")
    (git_kb["root"] / "local.txt").write_text("local only\n", encoding="utf-8")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "local")

    result = _publish(git_kb, hub_worktree, monkeypatch)
    assert result.exit_code == 0, result.output


def test_dev_publish_no_remote_refuses(git_kb, hub_worktree, monkeypatch):
    (git_kb["kb"] / "config.yaml").write_text("kind: dev\n", encoding="utf-8")

    msg = "no origin remote — kb publish in a dev repo needs one to check it is current"
    with pytest.raises(publish_mod.PublishError) as exc:
        publish_mod.ensure_current(git_kb["root"])
    assert str(exc.value) == msg

    result = _publish(git_kb, hub_worktree, monkeypatch)
    assert result.exit_code == 1
    assert msg in result.output


def test_dev_publish_fetch_failure_refuses(git_kb, run_git, tmp_path):
    _with_origin(git_kb, run_git, tmp_path, "dev")
    run_git(git_kb["root"], "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    branch = _branch(git_kb["root"], run_git)
    run_git(
        git_kb["root"],
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        f"refs/remotes/origin/{branch}",
    )

    with pytest.raises(publish_mod.PublishError) as exc:
        publish_mod.ensure_current(git_kb["root"])
    assert str(exc.value).startswith(f"could not fetch origin/{branch}: ")


def test_child_publish_unchanged(git_kb, hub_worktree, run_git, tmp_path, monkeypatch):
    other = _with_origin(git_kb, run_git, tmp_path, "child")
    _push_from(other, run_git)

    result = _publish(git_kb, hub_worktree, monkeypatch)
    assert result.exit_code == 0, result.output
