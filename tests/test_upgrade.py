import json
from pathlib import Path

import pytest

from strata_kb import __version__, gitio
from strata_kb.errors import KbError
from strata_kb.initcmd import init_repo
from strata_kb.llm import AUTO_TASK_ENV
from strata_kb.upgradecmd import upgrade

BRANCH = f"kb/upgrade-{__version__}"
SETTINGS = ".claude/settings.json"


@pytest.fixture
def repo(tmp_path, run_git, monkeypatch):
    """A ba repo, scaffolded and pushed to a bare origin."""
    monkeypatch.delenv(AUTO_TASK_ENV, raising=False)
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "ba-repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    run_git(root, "config", "commit.gpgsign", "false")
    init_repo(root, "ba")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    run_git(root, "push", "-u", "origin", "HEAD")
    run_git(root, "remote", "set-head", "origin", gitio.current_branch(root))
    return root


def _stale(root: Path, run_git) -> None:
    """Commit a repo that lacks the guard Stop hook, as a pre-sprint one does."""
    path = root / SETTINGS
    data = json.loads(path.read_text(encoding="utf-8"))
    data["hooks"]["Stop"] = [
        e for e in data["hooks"]["Stop"] if "guard" not in json.dumps(e)
    ]
    data["hooks"]["Stop"].append(
        {"hooks": [{"type": "command", "command": "echo mine"}]}
    )
    data["permissions"]["allow"].append("Bash(my-tool *)")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "stale")


def _fake_opener(calls):
    def opener(root, title, body, head=None, base=None):
        calls.append({"title": title, "body": body, "head": head, "base": base})
        return {"url": "https://example.test/pr/1"}

    return opener


def test_upgrade_refuses_dirty_tree(repo):
    (repo / "scratch.txt").write_text("x", encoding="utf-8")
    with pytest.raises(KbError, match="uncommitted"):
        upgrade(repo, open_pr=False)


def test_upgrade_refuses_in_auto_task(repo, monkeypatch):
    monkeypatch.setenv(AUTO_TASK_ENV, "1")
    with pytest.raises(KbError, match="auto"):
        upgrade(repo, open_pr=False)


def test_upgrade_refuses_wrong_kind(tmp_path, run_git, monkeypatch):
    monkeypatch.delenv(AUTO_TASK_ENV, raising=False)
    root = tmp_path / "hub"
    root.mkdir()
    run_git(root, "init")
    init_repo(root, "hub")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    with pytest.raises(KbError, match="ba or dev"):
        upgrade(root, open_pr=False)


def test_upgrade_refuses_existing_local_branch(repo, run_git):
    run_git(repo, "branch", BRANCH)
    with pytest.raises(KbError, match="already exists"):
        upgrade(repo, open_pr=False)


def test_upgrade_refuses_existing_remote_branch(repo, run_git):
    run_git(repo, "push", "origin", f"HEAD:refs/heads/{BRANCH}")
    with pytest.raises(KbError, match="already exists"):
        upgrade(repo, open_pr=False)


def test_upgrade_no_change_leaves_no_branch(repo, run_git):
    before = gitio.current_branch(repo)
    result = upgrade(repo, open_pr=False)
    assert result.branch is None and result.pr_url is None
    assert gitio.current_branch(repo) == before
    assert BRANCH not in run_git(repo, "branch")


def test_upgrade_commits_and_opens_pr(repo, run_git):
    _stale(repo, run_git)
    base = gitio.current_branch(repo)
    calls: list[dict] = []
    result = upgrade(repo, opener=_fake_opener(calls))
    assert result.branch == BRANCH
    assert result.pr_url == "https://example.test/pr/1"
    assert calls[0]["title"] == f"chore: kb upgrade to {__version__}"
    assert calls[0]["head"] == BRANCH and calls[0]["base"] == base
    assert SETTINGS in calls[0]["body"]
    assert gitio.remote_branch_exists(repo, BRANCH)
    assert gitio.current_branch(repo) == base


def test_upgrade_no_pr_stops_after_commit(repo, run_git):
    _stale(repo, run_git)
    calls: list[dict] = []
    result = upgrade(repo, open_pr=False, opener=_fake_opener(calls))
    assert result.branch == BRANCH and result.pr_url is None
    assert calls == []
    assert gitio.current_branch(repo) == BRANCH
    assert not gitio.remote_branch_exists(repo, BRANCH)
    assert "kb upgrade" in run_git(repo, "log", "-1", "--format=%s")


def test_upgrade_keeps_user_settings(repo, run_git):
    _stale(repo, run_git)
    upgrade(repo, open_pr=False)
    data = json.loads((repo / SETTINGS).read_text(encoding="utf-8"))
    assert "Bash(my-tool *)" in data["permissions"]["allow"]
    stop = json.dumps(data["hooks"]["Stop"])
    assert "echo mine" in stop and "kb guard stop" in stop


def test_upgrade_failure_returns_to_original_branch(repo, run_git):
    _stale(repo, run_git)
    base = gitio.current_branch(repo)

    def boom(*_a, **_k):
        raise KbError("gh down")

    with pytest.raises(KbError, match=BRANCH):
        upgrade(repo, opener=boom)
    assert gitio.current_branch(repo) == base
    assert BRANCH in run_git(repo, "branch")
