import subprocess

import pytest

from center_kb import ghio


def _proc(returncode: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=["gh"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


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
