import subprocess

import pytest

from strata_kb import ghio


def _proc(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_run_gh_passes_a_timeout(tmp_path, monkeypatch):
    """The `except TimeoutExpired` branch is worthless without this.

    Its handler is separately tested, but a subprocess.run with no timeout=
    never expires, so dropping the argument silently restores the hang this
    guards against while every other ghio test stays green.
    """
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs)
        return _proc(0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    ghio._run_gh(tmp_path, "repo", "view")
    assert seen["timeout"] == ghio._GH_TIMEOUT_SECONDS
    assert seen["timeout"] > 0


def test_run_gh_turns_a_hang_into_a_failed_probe(tmp_path, monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    proc = ghio._run_gh(tmp_path, "repo", "view")
    assert proc.returncode != 0
    assert "timed out" in proc.stderr
    # and the callers must read that as "no", not crash
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    assert ghio.can_open_pr(tmp_path) is False
    assert ghio.pr_url_for_branch(tmp_path, "publish/x") == ""


def test_pr_url_for_branch_found(tmp_path, monkeypatch):
    monkeypatch.setattr(
        ghio, "_run_gh",
        lambda root, *a: _proc(0, "https://github.com/org/hub/pull/7\n"),
    )
    assert ghio.pr_url_for_branch(tmp_path, "publish/x") == "https://github.com/org/hub/pull/7"


def test_pr_url_for_branch_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(1, "", "no pr"))
    assert ghio.pr_url_for_branch(tmp_path, "publish/x") == ""


def test_create_pr_returns_url(tmp_path, monkeypatch):
    seen: dict = {}

    def fake(root, *args):
        seen["args"] = args
        return _proc(0, "https://github.com/org/hub/pull/9\n")

    monkeypatch.setattr(ghio, "_run_gh", fake)
    url = ghio.create_pr(tmp_path, "publish/x", title="t", body="b")
    assert url == "https://github.com/org/hub/pull/9"
    assert seen["args"][:2] == ("pr", "create")


def test_create_pr_failure_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(1, "", "boom"))
    with pytest.raises(ghio.GHError):
        ghio.create_pr(tmp_path, "publish/x", title="t", body="b")


def test_can_open_pr_is_false_without_gh(tmp_path, monkeypatch):
    from strata_kb import ghio

    monkeypatch.setattr(ghio, "gh_available", lambda: False)
    assert ghio.can_open_pr(tmp_path) is False


def test_can_open_pr_is_true_when_gh_repo_view_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(0, '{"name": "hub"}'))
    assert ghio.can_open_pr(tmp_path) is True


def test_can_open_pr_is_false_when_gh_repo_view_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ghio, "gh_available", lambda: True)
    monkeypatch.setattr(ghio, "_run_gh", lambda root, *a: _proc(1, "", "not found"))
    assert ghio.can_open_pr(tmp_path) is False


def test_run_gh_returns_synthetic_failure_on_timeout(tmp_path, monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=ghio._GH_TIMEOUT_SECONDS)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    proc = ghio._run_gh(tmp_path, "repo", "view", "--json", "name")
    assert proc.returncode == 124
    assert "timed out" in proc.stderr
