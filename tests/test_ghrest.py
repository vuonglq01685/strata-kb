"""ghrest: `gh pr` replacement over `gh api` REST -- GraphQL is blocked on Claude Code cloud."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from strata_kb import ghrest
from strata_kb.ghio import GHError
from tests._fake_gh import FakeGh, make_repo, rest_pr

GH_KEYS = {"number", "url", "state", "mergedAt", "title", "body", "headRefName"}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


@pytest.fixture
def fake_gh(monkeypatch) -> FakeGh:
    fake = FakeGh()
    monkeypatch.setattr(ghrest, "_gh", fake)
    return fake


@pytest.mark.parametrize(
    ("remote", "expected"),
    [
        ("git@github.com:o/r.git", ("github.com", "o/r")),
        ("https://github.com/o/r", ("github.com", "o/r")),
        ("https://x-access-token:tok@github.com/o/r.git", ("github.com", "o/r")),
        ("https://ghe.corp/o/r", ("ghe.corp", "o/r")),
        ("ssh://git@ghe.corp:2222/o/r.git", ("ghe.corp", "o/r")),
    ],
)
def test_origin_slug_scp_https_and_ghe(tmp_path, remote, expected):
    assert ghrest.origin_slug(make_repo(tmp_path, remote)) == expected


def test_origin_slug_without_origin_raises(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    with pytest.raises(GHError, match="origin"):
        ghrest.origin_slug(tmp_path)


def test_api_sends_host_method_path_and_json_body_on_stdin(root, fake_gh):
    fake_gh.on("POST", "pulls", {"ok": 1})
    assert ghrest.api(root, "POST", "repos/o/r/pulls", {"a": "é"}) == {"ok": 1}
    call = fake_gh.calls[0]
    assert (call.host, call.method, call.path) == (
        "github.com",
        "POST",
        "repos/o/r/pulls",
    )
    assert call.body == {"a": "é"}


def test_api_empty_output_is_none_and_bad_json_raises(root, monkeypatch):
    monkeypatch.setattr(ghrest, "_gh", lambda *a, **k: "")
    assert ghrest.api(root, "DELETE", "repos/o/r/git/refs/heads/x") is None
    monkeypatch.setattr(ghrest, "_gh", lambda *a, **k: "<html>")
    with pytest.raises(GHError, match="JSON"):
        ghrest.api(root, "GET", "repos/o/r")


def test_gh_has_60s_timeout_and_maps_failures_to_gherror(root, monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(ghrest.subprocess, "run", fake_run)
    with pytest.raises(GHError, match="timed out"):
        ghrest._gh(root, ["api", "x"], None)
    assert seen["timeout"] == 60

    def nonzero(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "HTTP 404")

    monkeypatch.setattr(ghrest.subprocess, "run", nonzero)
    with pytest.raises(GHError, match="HTTP 404"):
        ghrest._gh(root, ["api", "x"], None)

    def missing(cmd, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(ghrest.subprocess, "run", missing)
    with pytest.raises(GHError, match="gh not found"):
        ghrest._gh(root, ["api", "x"], None)


def test_find_encodes_head_with_slash(root, fake_gh):
    fake_gh.on("GET", "pulls", [])
    ghrest.find_prs(root, "auto/US-1", "open")
    path = fake_gh.calls[0].path
    assert path.startswith("repos/o/r/pulls?")
    assert "head=o%3Aauto%2FUS-1" in path
    assert "state=open" in path
    assert "per_page=100" in path


def test_find_returns_gh_shaped_dicts(root, fake_gh):
    fake_gh.on("GET", "pulls", [rest_pr(), rest_pr(number=8, state="closed")])
    prs = ghrest.find_prs(root, "auto/US-1", "all")
    assert all(set(p) >= GH_KEYS for p in prs)
    assert [p["state"] for p in prs] == ["OPEN", "CLOSED"]
    assert prs[0]["url"] == "https://github.com/o/r/pull/7"
    assert prs[0]["headRefName"] == "auto/US-1"


def test_find_merged_filters_closed_on_merged_at(root, fake_gh):
    fake_gh.on(
        "GET",
        "pulls",
        [
            rest_pr(number=1, state="closed", merged_at="2026-01-01T00:00:00Z"),
            rest_pr(number=2, state="closed"),
        ],
    )
    prs = ghrest.find_prs(root, "auto/US-1", "merged")
    assert "state=closed" in fake_gh.calls[0].path
    assert [(p["number"], p["state"]) for p in prs] == [(1, "MERGED")]
    assert prs[0]["mergedAt"] == "2026-01-01T00:00:00Z"


def test_find_rejects_unknown_state(root, fake_gh):
    with pytest.raises(GHError, match="state"):
        ghrest.find_prs(root, "b", "bogus")


def test_null_body_becomes_empty_string(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr(body=None))
    assert ghrest.view_pr(root, "7")["body"] == ""


def test_view_by_number_branch_and_current_branch(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    assert ghrest.view_pr(root, "7")["number"] == 7
    assert ghrest.view_pr(root, "#7")["number"] == 7

    fake_gh.on(
        "GET", "head=", [rest_pr(number=3), rest_pr(number=9), rest_pr(number=5)]
    )
    assert ghrest.view_pr(root, "auto/US-1")["number"] == 9  # newest wins
    assert "state=all" in fake_gh.calls[-1].path
    assert ghrest.view_pr(root)["number"] == 9  # current branch is auto/US-1
    assert "auto%2FUS-1" in fake_gh.calls[-1].path


def test_view_without_pr_raises(root, fake_gh):
    fake_gh.on("GET", "head=", [])
    with pytest.raises(GHError, match="no pull request"):
        ghrest.view_pr(root, "nope")


def test_open_posts_with_defaults_from_git(root, fake_gh):
    fake_gh.on("POST", "pulls", rest_pr())
    pr = ghrest.open_pr(root, "T", "B")
    call = fake_gh.calls[0]
    assert call.path == "repos/o/r/pulls"
    assert call.body == {"title": "T", "body": "B", "head": "auto/US-1", "base": "main"}
    assert set(pr) >= GH_KEYS


def test_open_honours_explicit_head_and_base(root, fake_gh):
    fake_gh.on("POST", "pulls", rest_pr())
    ghrest.open_pr(root, "T", "B", head="h", base="dev")
    assert fake_gh.calls[0].body["head"] == "h"
    assert fake_gh.calls[0].body["base"] == "dev"


def test_checks_combines_check_runs_and_statuses(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr(sha="s1"))
    fake_gh.on(
        "GET",
        "commits/s1/check-runs",
        {
            "check_runs": [
                {"name": "a", "status": "completed", "conclusion": "success"},
                {"name": "b", "status": "completed", "conclusion": "skipped"},
                {"name": "c", "status": "completed", "conclusion": "failure"},
                {"name": "d", "status": "in_progress", "conclusion": None},
                {"name": "e", "status": "completed", "conclusion": "timed_out"},
            ]
        },
    )
    fake_gh.on(
        "GET",
        "commits/s1/status",
        {
            "statuses": [
                {"context": "ci/x", "state": "success"},
                {"context": "ci/y", "state": "error"},
                {"context": "ci/z", "state": "pending"},
            ]
        },
    )
    assert {c["name"]: c["state"] for c in ghrest.checks(root, "7")} == {
        "a": "success",
        "b": "success",
        "c": "failure",
        "d": "pending",
        "e": "failure",
        "ci/x": "success",
        "ci/y": "failure",
        "ci/z": "pending",
    }


@pytest.mark.parametrize(
    ("states", "code"),
    [
        ([], 8),
        (["success", "success"], 0),
        (["success", "pending"], 8),
        (["pending", "failure"], 1),
    ],
)
def test_exit_code_for_check_states(states, code):
    assert ghrest.exit_code([{"name": "x", "state": s} for s in states]) == code


def test_wait_for_checks_polls_until_settled(root, monkeypatch):
    # 0 runs, then pending, then success -> done after 3 polls
    polls = iter(
        [[], [{"name": "a", "state": "pending"}], [{"name": "a", "state": "success"}]]
    )
    monkeypatch.setattr(ghrest, "checks", lambda *a, **k: next(polls))
    slept = []
    code, rows = ghrest.wait_for_checks(
        root, "7", interval=5, timeout=100, sleep=slept.append
    )
    assert (code, rows[0]["state"]) == (0, "success")
    assert slept == [5, 5]


def test_wait_for_checks_times_out_with_8(root, monkeypatch):
    monkeypatch.setattr(ghrest, "checks", lambda *a, **k: [])
    now = [0.0]

    def sleep(s):
        now[0] += s

    code, rows = ghrest.wait_for_checks(
        root, None, interval=10, timeout=25, sleep=sleep, clock=lambda: now[0]
    )
    assert (code, rows) == (8, [])
    assert now[0] <= 35


def test_merge_deletes_branch_when_asked(root, fake_gh):
    fake_gh.on(
        "GET",
        "pulls/7",
        rest_pr(),
        rest_pr(state="closed", merged_at="2026-01-01T00:00:00Z"),
    )
    fake_gh.on("PUT", "pulls/7/merge", {"merged": True})
    fake_gh.on("DELETE", "git/refs/heads/", None)
    pr = ghrest.merge_pr(root, "7", "squash", delete_branch=True)
    ops = [(c.method, c.path) for c in fake_gh.calls]
    assert ("PUT", "repos/o/r/pulls/7/merge") in ops
    assert ops[-1] == ("DELETE", "repos/o/r/git/refs/heads/auto/US-1")
    put = next(c for c in fake_gh.calls if c.method == "PUT")
    assert put.body == {"merge_method": "squash"}
    assert pr["state"] == "MERGED"


@pytest.mark.parametrize(
    ("head_repo", "deleted"),
    [("o/r", True), ("O/R", True), ("fork/r", False), (None, False)],
)
def test_merge_delete_branch_only_for_same_repo_heads(
    root, fake_gh, head_repo, deleted
):
    fake_gh.on("GET", "pulls/7", rest_pr(head="dev", head_repo=head_repo))
    fake_gh.on("PUT", "pulls/7/merge", {"merged": True})
    fake_gh.on("DELETE", "git/refs/heads/", None)
    ghrest.merge_pr(root, "7", delete_branch=True)
    deletes = [c.path for c in fake_gh.calls if c.method == "DELETE"]
    assert deletes == (["repos/o/r/git/refs/heads/dev"] if deleted else [])


def test_merge_keeps_branch_by_default(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    fake_gh.on("PUT", "pulls/7/merge", {"merged": True})
    ghrest.merge_pr(root, "7")
    assert all(c.method != "DELETE" for c in fake_gh.calls)


def test_merge_not_merged_raises_and_keeps_branch(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    fake_gh.on("PUT", "pulls/7/merge", {"merged": False, "message": "not mergeable"})
    with pytest.raises(GHError, match="not mergeable"):
        ghrest.merge_pr(root, "7", delete_branch=True)
    assert all(c.method != "DELETE" for c in fake_gh.calls)


def test_merge_rejects_unknown_method(root, fake_gh):
    with pytest.raises(GHError, match="merge method"):
        ghrest.merge_pr(root, "7", "bogus")


def test_edit_patches_only_given_fields(root, fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    fake_gh.on("PATCH", "pulls/7", rest_pr(title="N"))
    pr = ghrest.edit_pr(root, "7", title="N")
    patch = next(c for c in fake_gh.calls if c.method == "PATCH")
    assert patch.body == {"title": "N"}
    assert pr["title"] == "N"


def test_edit_with_nothing_to_change_raises(root, fake_gh):
    with pytest.raises(GHError, match="nothing to edit"):
        ghrest.edit_pr(root, "7")
