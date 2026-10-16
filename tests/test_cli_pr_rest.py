"""`kb pr find|view|open|checks|merge|edit` -- thin CLI over ghrest."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from strata_kb import ghrest
from strata_kb.cli import app
from tests._fake_gh import FakeGh, make_repo, rest_pr

runner = CliRunner()


@pytest.fixture
def fake_gh(tmp_path, monkeypatch) -> FakeGh:
    make_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    fake = FakeGh()
    monkeypatch.setattr(ghrest, "_gh", fake)
    return fake


def test_view_json_has_gh_keys(fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    result = runner.invoke(app, ["pr", "view", "7", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert {
        "number",
        "url",
        "state",
        "mergedAt",
        "title",
        "body",
        "headRefName",
    } <= set(data)
    assert data["state"] == "OPEN"


def test_view_prints_url(fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    result = runner.invoke(app, ["pr", "view", "7"])
    assert result.output.strip() == "https://github.com/o/r/pull/7"


def test_find_prints_one_url_per_pr_and_json_list(fake_gh):
    fake_gh.on("GET", "pulls", [rest_pr(number=1), rest_pr(number=2)])
    result = runner.invoke(app, ["pr", "find", "--head", "auto/US-1"])
    assert result.output.split() == [
        "https://github.com/o/r/pull/1",
        "https://github.com/o/r/pull/2",
    ]
    result = runner.invoke(
        app, ["pr", "find", "--head", "auto/US-1", "--state", "all", "--json"]
    )
    assert [p["number"] for p in json.loads(result.output)] == [1, 2]


def test_find_requires_head(fake_gh):
    assert runner.invoke(app, ["pr", "find"]).exit_code != 0


def test_open_reads_body_file_and_prints_url(fake_gh, tmp_path):
    body = tmp_path / "b.md"
    body.write_text("## Ticket\nx", encoding="utf-8")
    fake_gh.on("POST", "pulls", rest_pr())
    result = runner.invoke(
        app, ["pr", "open", "--title", "T", "--body-file", str(body), "--base", "dev"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "https://github.com/o/r/pull/7"
    assert fake_gh.calls[0].body["body"] == "## Ticket\nx"
    assert fake_gh.calls[0].body["base"] == "dev"


def test_open_needs_exactly_one_body_source(fake_gh, tmp_path):
    f = tmp_path / "b.md"
    f.write_text("x", encoding="utf-8")
    assert runner.invoke(app, ["pr", "open", "--title", "T"]).exit_code == 1
    both = ["pr", "open", "--title", "T", "--body", "s", "--body-file", str(f)]
    assert runner.invoke(app, both).exit_code == 1
    assert fake_gh.calls == []


def test_open_body_file_dash_reads_stdin(fake_gh):
    fake_gh.on("POST", "pulls", rest_pr())
    result = runner.invoke(
        app, ["pr", "open", "--title", "T", "--body-file", "-"], input="from stdin"
    )
    assert result.exit_code == 0, result.output
    assert fake_gh.calls[0].body["body"] == "from stdin"


def _checks_routes(fake_gh, *runs_per_poll):
    fake_gh.on("GET", "pulls/7", rest_pr(sha="s1"))
    fake_gh.on("GET", "check-runs", *[{"check_runs": r} for r in runs_per_poll])
    fake_gh.on("GET", "/status", {"statuses": []})


def _run(name, status, conclusion=None):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_checks_all_success_exits_0_one_line_per_check(fake_gh):
    _checks_routes(fake_gh, [_run("a", "completed", "success")])
    result = runner.invoke(app, ["pr", "checks", "7"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().split("\t") == ["a", "success"]


def test_checks_failure_exits_1(fake_gh):
    _checks_routes(fake_gh, [_run("a", "completed", "failure")])
    assert runner.invoke(app, ["pr", "checks", "7"]).exit_code == 1


def test_checks_pending_without_watch_exits_8(fake_gh):
    _checks_routes(fake_gh, [_run("a", "in_progress")])
    assert runner.invoke(app, ["pr", "checks", "7"]).exit_code == 8


def test_checks_watch_waits_while_no_check_run_exists(fake_gh, monkeypatch):
    _checks_routes(
        fake_gh, [], [_run("a", "in_progress")], [_run("a", "completed", "success")]
    )
    monkeypatch.setattr(ghrest.time, "sleep", lambda s: None)
    result = runner.invoke(app, ["pr", "checks", "7", "--watch", "--interval", "1"])
    assert result.exit_code == 0, result.output
    polls = [c for c in fake_gh.calls if "check-runs" in c.path]
    assert len(polls) == 3


def test_merge_squash_with_admin_and_delete_branch(fake_gh):
    fake_gh.on(
        "GET",
        "pulls/7",
        rest_pr(),
        rest_pr(state="closed", merged_at="2026-01-01T00:00:00Z"),
    )
    fake_gh.on("PUT", "pulls/7/merge", {"merged": True})
    fake_gh.on("DELETE", "git/refs/heads/", None)
    result = runner.invoke(
        app, ["pr", "merge", "7", "--squash", "--admin", "--delete-branch"]
    )
    assert result.exit_code == 0, result.output
    put = next(c for c in fake_gh.calls if c.method == "PUT")
    assert put.body == {"merge_method": "squash"}
    assert fake_gh.calls[-1].method == "DELETE"


def test_merge_flag_selects_merge_commit(fake_gh):
    fake_gh.on("GET", "pulls/7", rest_pr())
    fake_gh.on("PUT", "pulls/7/merge", {"merged": True})
    assert runner.invoke(app, ["pr", "merge", "7", "--merge"]).exit_code == 0
    put = next(c for c in fake_gh.calls if c.method == "PUT")
    assert put.body == {"merge_method": "merge"}


def test_merge_both_flags_is_an_error(fake_gh):
    assert (
        runner.invoke(app, ["pr", "merge", "7", "--squash", "--merge"]).exit_code == 1
    )


def test_edit_title_and_body_file(fake_gh, tmp_path):
    f = tmp_path / "b.md"
    f.write_text("new body", encoding="utf-8")
    fake_gh.on("GET", "pulls/7", rest_pr())
    fake_gh.on("PATCH", "pulls/7", rest_pr())
    result = runner.invoke(
        app, ["pr", "edit", "7", "--title", "N", "--body-file", str(f)]
    )
    assert result.exit_code == 0, result.output
    patch = next(c for c in fake_gh.calls if c.method == "PATCH")
    assert patch.body == {"title": "N", "body": "new body"}


def test_gh_failure_is_one_line_exit_1(fake_gh):
    from strata_kb.ghio import GHError

    fake_gh.on("GET", "pulls/7", GHError("gh api failed: HTTP 404"))
    result = runner.invoke(app, ["pr", "view", "7"])
    assert result.exit_code == 1
    assert "HTTP 404" in result.output
    assert "Traceback" not in result.output


def test_lint_still_registered():
    assert runner.invoke(app, ["pr", "--help"]).output.count("lint") >= 1
