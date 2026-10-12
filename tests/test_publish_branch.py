"""`kb publish --branch`: the hub's self-publish on its own rolling branch."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from strata_kb import gitio
from strata_kb.cli import app
from strata_kb.publish import PublishError, publish

BRANCH = "kb-bot/code-sync"
runner = CliRunner()


@pytest.fixture
def hub_on_branch(hub_with_origin, run_git):
    """Self-publishing hub, origin/HEAD set, checked out on BRANCH with a prior commit."""
    hub = hub_with_origin
    default = run_git(hub, "rev-parse", "--abbrev-ref", "HEAD")
    run_git(hub, "remote", "set-head", "origin", default)
    (hub / ".kb" / "config.yaml").write_text("kind: hub\nhub: .\n", encoding="utf-8")
    run_git(hub, "checkout", "-b", BRANCH)
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "kb: prior code-sync commit")
    return hub


@pytest.fixture
def gh(monkeypatch):
    """can_open_pr True, no open PR; records create_pr and push_branch calls."""
    calls = {"create": [], "push": []}
    monkeypatch.setattr("strata_kb.ghio.can_open_pr", lambda root: True)
    monkeypatch.setattr("strata_kb.ghio.pr_url_for_branch", lambda root, b: "")

    def create_pr(root, branch, title, body):
        calls["create"].append(branch)
        return "https://example.test/pull/1"

    monkeypatch.setattr("strata_kb.ghio.create_pr", create_pr)
    real_push = gitio.push_branch

    def push(root, branch, token=None, **kw):
        calls["push"].append(kw)
        return real_push(root, branch, token, **kw)

    monkeypatch.setattr(gitio, "push_branch", push)
    return calls


def _changed_files(run_git, hub, rev="HEAD"):
    out = run_git(hub, "show", "--name-only", "--format=", rev)
    return [line for line in out.splitlines() if line]


def test_branch_publish_commits_on_current_branch_without_reset(
    hub_on_branch, gh, run_git
):
    hub = hub_on_branch
    prior = run_git(hub, "rev-parse", "HEAD")
    report = publish(hub / ".kb", str(hub), mode="pr", self_publish=True, branch=BRANCH)
    assert (
        run_git(hub, "merge-base", "--is-ancestor", prior, "HEAD") == ""
    )  # raises on failure
    assert run_git(hub, "rev-parse", "HEAD") != prior
    assert _changed_files(run_git, hub)
    assert all(f.startswith("federation/") for f in _changed_files(run_git, hub))
    assert run_git(hub, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert gh["push"] == [{"force": False}]
    assert gh["create"] == [BRANCH]
    assert report.pr_url == "https://example.test/pull/1"
    assert run_git(hub, "rev-parse", f"origin/{BRANCH}") == run_git(
        hub, "rev-parse", "HEAD"
    )


def test_baseline_only_commit_is_pushed_and_gets_a_pr(hub_on_branch, gh, run_git):
    hub = hub_on_branch
    publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    gh["create"].clear()
    # a later round changes no mirror content, only the baseline file
    (hub / "kb-code-sync.yaml").write_text("baseline: abc\n", encoding="utf-8")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "kb: baseline")
    head = run_git(hub, "rev-parse", "HEAD")
    report = publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert run_git(hub, "rev-parse", "HEAD") == head  # no new commit
    assert run_git(hub, "rev-parse", f"origin/{BRANCH}") == head
    assert report.pushed and gh["create"] == [BRANCH]


def test_rerun_after_a_failed_push_still_pushes(
    hub_on_branch, gh, monkeypatch, run_git
):
    hub = hub_on_branch
    real_push = gitio.push_branch

    def failing(*a, **kw):
        raise gitio.GitError("push branch failed: network")

    monkeypatch.setattr(gitio, "push_branch", failing)
    with pytest.raises(gitio.GitError):
        publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    head = run_git(hub, "rev-parse", "HEAD")  # federation commit exists locally
    monkeypatch.setattr(gitio, "push_branch", real_push)
    report = publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert run_git(hub, "rev-parse", "HEAD") == head
    assert run_git(hub, "rev-parse", f"origin/{BRANCH}") == head
    assert report.pushed and report.pr_url


def test_up_to_date_branch_does_not_push_again(hub_on_branch, gh):
    hub = hub_on_branch
    publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    gh["push"].clear()
    report = publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert gh["push"] == [] and not report.pushed


def test_branch_publish_reuses_open_pr(hub_on_branch, gh, monkeypatch):
    hub = hub_on_branch
    monkeypatch.setattr(
        "strata_kb.ghio.pr_url_for_branch",
        lambda root, b: "https://example.test/pull/9",
    )
    report = publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert gh["create"] == []
    assert report.pr_url == "https://example.test/pull/9"


def test_branch_must_be_checked_out(hub_on_branch, gh, run_git):
    hub = hub_on_branch
    other = run_git(hub, "rev-parse", "--abbrev-ref", "origin/HEAD").split("/")[-1]
    run_git(hub, "checkout", other)
    head = run_git(hub, "rev-parse", "HEAD")
    with pytest.raises(PublishError) as exc:
        publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert BRANCH in str(exc.value) and other in str(exc.value)
    assert run_git(hub, "rev-parse", "HEAD") == head


def test_branch_refuses_when_gh_cannot_open_a_pr(
    hub_on_branch, gh, monkeypatch, run_git
):
    hub = hub_on_branch
    head = run_git(hub, "rev-parse", "HEAD")
    monkeypatch.setattr("strata_kb.ghio.can_open_pr", lambda root: False)
    with pytest.raises(PublishError, match="PR"):
        publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert run_git(hub, "rev-parse", "HEAD") == head
    assert gh["push"] == []


def test_branch_refuses_when_hub_has_no_remote(hub_worktree, gh, run_git):
    hub = hub_worktree
    run_git(hub, "checkout", "-b", BRANCH)
    head = run_git(hub, "rev-parse", "HEAD")
    with pytest.raises(PublishError, match="remote"):
        publish(hub / ".kb", str(hub), self_publish=True, branch=BRANCH)
    assert run_git(hub, "rev-parse", "HEAD") == head


def test_branch_refuses_the_default_branch(hub_with_origin, gh, run_git):
    hub = hub_with_origin
    default = run_git(hub, "rev-parse", "--abbrev-ref", "HEAD")
    run_git(hub, "remote", "set-head", "origin", default)
    head = run_git(hub, "rev-parse", "HEAD")
    with pytest.raises(PublishError, match="default branch"):
        publish(hub / ".kb", str(hub), self_publish=True, branch=default)
    assert run_git(hub, "rev-parse", "HEAD") == head
    assert gh["push"] == []


def test_branch_head_on_a_detached_checkout_is_refused(hub_on_branch, gh, run_git):
    hub = hub_on_branch
    run_git(hub, "checkout", "--detach")
    head = run_git(hub, "rev-parse", "HEAD")
    with pytest.raises(PublishError, match="not a valid branch name"):
        publish(hub / ".kb", str(hub), self_publish=True, branch="HEAD")
    assert run_git(hub, "rev-parse", "HEAD") == head
    assert gh["push"] == []


def test_branch_with_an_invalid_name_is_refused(hub_on_branch, gh, run_git):
    hub = hub_on_branch
    head = run_git(hub, "rev-parse", "HEAD")
    with pytest.raises(PublishError, match="not a valid branch name"):
        publish(hub / ".kb", str(hub), self_publish=True, branch="a..b")
    assert run_git(hub, "rev-parse", "HEAD") == head


def test_branch_refuses_non_self_publish(git_kb, hub_with_origin, gh):
    with pytest.raises(PublishError, match="self-publish"):
        publish(git_kb["kb"], str(hub_with_origin), repo_id="demo-kb", branch=BRANCH)


def _cli(hub, *args):
    return runner.invoke(
        app, ["publish", "--kb-dir", str(hub / ".kb"), "--branch", BRANCH, *args]
    )


def test_cli_branch_refuses_direct(hub_on_branch, gh, run_git):
    head = run_git(hub_on_branch, "rev-parse", "HEAD")
    result = _cli(hub_on_branch, "--direct")
    assert result.exit_code == 1 and "--direct" in result.output
    assert run_git(hub_on_branch, "rev-parse", "HEAD") == head


def test_cli_branch_refuses_intake_route(hub_on_branch, gh):
    (hub_on_branch / ".kb" / "config.yaml").write_text(
        "kind: hub\nhub: .\nintake: https://hub.example\n", encoding="utf-8"
    )
    result = _cli(hub_on_branch)
    assert result.exit_code == 1 and "intake" in result.output


def test_cli_branch_refuses_federation_route(hub_on_branch, gh, tmp_path, run_git):
    upper = tmp_path / "upper"
    upper.mkdir()
    (hub_on_branch / ".kb" / "config.yaml").write_text(
        f"kind: hub\nhub: {upper}\n", encoding="utf-8"
    )
    result = _cli(hub_on_branch)
    assert result.exit_code == 1 and "self-publish" in result.output


def test_cli_branch_refuses_non_self_publish(git_kb, hub_with_origin, gh):
    (git_kb["kb"] / "config.yaml").write_text(
        f"kind: child\nhub: {hub_with_origin}\n", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["publish", "--kb-dir", str(git_kb["kb"]), "--branch", BRANCH]
    )
    assert result.exit_code == 1 and "self-publish" in result.output


def test_cli_branch_publishes_and_prints_pr(hub_on_branch, gh):
    result = _cli(hub_on_branch)
    assert result.exit_code == 0, result.output
    assert "https://example.test/pull/1" in result.output


def test_plain_self_publish_still_uses_publish_rid_branch(
    hub_with_origin, monkeypatch, run_git
):
    hub = hub_with_origin
    (hub / ".kb" / "config.yaml").write_text("kind: hub\nhub: .\n", encoding="utf-8")
    created = []
    monkeypatch.setattr("strata_kb.ghio.can_open_pr", lambda root: True)
    monkeypatch.setattr("strata_kb.ghio.pr_url_for_branch", lambda root, b: "")
    monkeypatch.setattr(
        "strata_kb.ghio.create_pr",
        lambda root, branch, title, body: created.append(branch) or "u",
    )
    report = publish(hub / ".kb", str(hub), mode="pr", self_publish=True)
    assert created == [f"publish/{hub.name}"]
    assert report.mode == "pr"
    assert run_git(hub, "ls-remote", "--heads", "origin", f"publish/{hub.name}")
