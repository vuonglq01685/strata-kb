import pytest

from center_kb import pubgate
from center_kb.publish import publish


@pytest.fixture
def hub_with_bare_remote(hub_worktree, run_git, tmp_path):
    """A hub whose origin is a bare repo -- i.e. a remote that is not GitHub."""
    origin = tmp_path / "hub-remote.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    return hub_worktree, origin


def test_auto_refuses_instead_of_pushing_to_a_non_github_remote(
    git_kb, hub_with_bare_remote, monkeypatch, run_git
):
    hub, origin = hub_with_bare_remote
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: False)
    before = run_git(origin, "rev-parse", "HEAD")
    with pytest.raises(pubgate.GateError) as exc:
        publish(git_kb["kb"], str(hub), repo_id="demo-kb")
    assert "--pr" in str(exc.value) and "--direct" in str(exc.value)
    assert run_git(origin, "rev-parse", "HEAD") == before


def test_explicit_direct_still_publishes_to_a_remote_hub(
    git_kb, hub_with_bare_remote, run_git, monkeypatch
):
    hub, origin = hub_with_bare_remote
    # Strongest stub: proves `direct` is chosen even when a PR is possible.
    # After item 2's _can_pr short-circuit this may not even be consulted for
    # an explicit --direct -- stub it anyway so the test does not silently
    # come to depend on that and shell out to a real `gh` on some other run.
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: True)
    report = publish(git_kb["kb"], str(hub), repo_id="demo-kb", mode="direct")
    assert report.mode == "direct"
    assert (hub / "federation" / "demo-kb" / "index.yaml").exists()


def test_auto_still_picks_direct_for_a_local_path_hub(git_kb, hub_worktree, monkeypatch):
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: True)
    report = publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    assert report.mode == "direct"


def test_pr_mode_refuses_before_pushing_when_gh_cannot_see_the_hub(
    git_kb, hub_with_bare_remote, monkeypatch, run_git
):
    hub, origin = hub_with_bare_remote
    monkeypatch.setattr("center_kb.ghio.gh_available", lambda: True)
    monkeypatch.setattr("center_kb.ghio.can_open_pr", lambda root: False)
    with pytest.raises(pubgate.GateError):
        publish(git_kb["kb"], str(hub), repo_id="demo-kb", mode="pr")
    branches = run_git(origin, "branch", "--list", "publish/demo-kb")
    assert branches.strip() == ""
