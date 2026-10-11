# tests/test_codesync_runner.py
from __future__ import annotations

import base64
import json
import logging

import pytest

from strata_kb import gitio
from strata_kb.codesync import baseline, runner, scan
from tests.test_cli_codesync import NO_LEDGER
from tests.test_codesync_changes import commit, write_doc
from tests.test_codesync_scan import _with_origin

REPO = "acme/kb-hub"


class RouteHTTP:
    """Fake GitHub: a baseline-file GET, an issue list, and issue writes."""

    def __init__(self, baseline_sha: str | None = None, open_issues=()):
        self.baseline_sha = baseline_sha
        self.open_issues = list(open_issues)
        self.requests: list[tuple[str, str]] = []

    def __call__(self, req):
        method, url = req.get_method(), req.full_url
        self.requests.append((method, url))
        if method == "GET" and "/contents/" in url:
            if self.baseline_sha is None:
                return 404, b"{}"
            text = f"baseline: {self.baseline_sha}\n".encode()
            body = {"encoding": "base64", "content": base64.b64encode(text).decode()}
            return 200, json.dumps(body).encode()
        if method == "GET":
            return 200, json.dumps(self.open_issues).encode()
        return 201, json.dumps({"number": 5}).encode()

    def methods(self) -> list[str]:
        return [m for m, _ in self.requests]


@pytest.fixture
def hub_with_drift(code_sync_hub, run_git, tmp_path, monkeypatch):
    """`(root, c1)`: baseline file = c1, origin pushed, github url set, code docs drifted since c1."""
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    baseline.write(root, c1)
    commit(root, run_git)
    _with_origin(root, run_git, tmp_path)
    run_git(root, "remote", "set-url", "origin", f"https://github.com/{REPO}.git")
    for name in ("STRATA_KB_GH_TOKEN", "STRATA_KB_GH_APP_ID", "STRATA_KB_GH_APP_KEY"):
        monkeypatch.delenv(name, raising=False)
    return root, c1


def test_run_once_with_creds_reads_bot_branch_baseline_over_rest(
    hub_with_drift, monkeypatch
):
    root, c1 = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "tok")
    http = RouteHTTP(baseline_sha=c1)
    seen: dict = {}
    real = scan.run_scan

    def spy(r, **kw):
        seen.update(kw)
        return real(r, **kw)

    monkeypatch.setattr(scan, "run_scan", spy)
    fetches: list[tuple] = []
    real_run = gitio._run

    def spy_run(r, *args, **kw):
        fetches.append(args) if args and args[0] == "fetch" else None
        return real_run(r, *args, **kw)

    monkeypatch.setattr(gitio, "_run", spy_run)

    code = runner.run_once(root, issue=True, http=http)

    assert code == 2
    assert seen == {"baseline_sha": c1, "baseline_source": "bot-branch"}
    assert not fetches
    assert http.methods() == ["GET", "GET", "POST", "POST"]
    assert f"/contents/{baseline.BASELINE_FILE}" in http.requests[0][1]
    assert f"ref={baseline.BOT_BRANCH.replace('/', '%2F')}" in http.requests[0][1]


def test_run_once_falls_back_to_resolve_when_bot_branch_has_no_file(
    hub_with_drift, monkeypatch, caplog
):
    root, c1 = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "tok")
    seen: dict = {}
    real = scan.run_scan

    def spy(r, **kw):
        seen.update(kw)
        return real(r, **kw)

    monkeypatch.setattr(scan, "run_scan", spy)

    runner.run_once(root, issue=True, http=RouteHTTP(baseline_sha=None))

    assert seen["baseline_sha"] is None


def test_run_once_without_creds_logs_and_returns(hub_with_drift, caplog):
    root, c1 = hub_with_drift
    http = RouteHTTP()
    with caplog.at_level(logging.INFO, logger="strata_kb.codesync.runner"):
        code = runner.run_once(root, issue=True, http=http)

    assert code == 2
    assert "issue not updated: no GitHub credentials" in caplog.text
    assert http.requests == []


def test_run_once_issue_false_never_touches_github(hub_with_drift, monkeypatch):
    root, c1 = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "tok")
    http = RouteHTTP()
    assert runner.run_once(root, issue=False, http=http) == 2
    assert http.requests == []


def test_run_once_non_github_remote_logs_and_returns(hub_with_drift, run_git, caplog):
    root, c1 = hub_with_drift
    run_git(root, "remote", "set-url", "origin", "https://example.com/x/y.git")
    with caplog.at_level(logging.INFO, logger="strata_kb.codesync.runner"):
        assert runner.run_once(root, issue=True, http=RouteHTTP()) == 2
    assert "issue not updated: " in caplog.text
    assert "not a GitHub repo URL" in caplog.text


def test_run_once_github_error_returns_scan_code_and_hides_token(
    hub_with_drift, monkeypatch, caplog
):
    root, c1 = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "sekret-token")

    def boom(req):
        return 500, b"{}"

    with caplog.at_level(logging.INFO, logger="strata_kb.codesync.runner"):
        code = runner.run_once(root, issue=True, http=boom)

    assert code == 2
    assert "issue not updated" in caplog.text
    assert "sekret-token" not in caplog.text


def test_scan_error_never_closes_issue(hub_with_drift, monkeypatch, caplog):
    root, _ = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "tok")
    # A sha that is valid hex but not in this repo's history.
    http = RouteHTTP(baseline_sha="deadbeefcafe1234", open_issues=[{"number": 9}])
    with caplog.at_level(logging.INFO, logger="strata_kb.codesync.runner"):
        code = runner.run_once(root, issue=True, http=http)

    assert code == 1
    assert "scan failed" in caplog.text
    assert set(http.methods()) == {"GET"}
    assert all("/issues" not in u for _, u in http.requests)


def test_scan_error_on_garbage_baseline_returns_1(hub_with_drift, monkeypatch):
    root, _ = hub_with_drift
    monkeypatch.setenv("STRATA_KB_GH_TOKEN", "tok")
    http = RouteHTTP(baseline_sha="not-hex!")
    assert runner.run_once(root, issue=True, http=http) == 1
    assert set(http.methods()) == {"GET"}


class StopLoop(Exception):
    pass


def test_run_loop_survives_errors_and_sleeps_interval(tmp_path, monkeypatch, caplog):
    calls: list[int] = []

    def flaky(root, *, issue, http):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return 0

    monkeypatch.setattr(runner, "run_once", flaky)
    sleeps: list[int] = []

    def sleep(n):
        sleeps.append(n)
        if len(sleeps) == 2:
            raise StopLoop

    with (
        caplog.at_level(logging.INFO, logger="strata_kb.codesync.runner"),
        pytest.raises(StopLoop),
    ):
        runner.run_loop(tmp_path, interval=3600, issue=True, sleep=sleep)

    assert len(calls) == 2
    assert sleeps == [3600, 3600]
    assert "RuntimeError: boom" in caplog.text


def test_interval_from_env_default(monkeypatch):
    monkeypatch.delenv("STRATA_KB_CODE_SYNC_INTERVAL", raising=False)
    assert runner.interval_from_env() == 86400


def test_interval_from_env_accepts_minimum(monkeypatch):
    monkeypatch.setenv("STRATA_KB_CODE_SYNC_INTERVAL", "60")
    assert runner.interval_from_env() == 60


@pytest.mark.parametrize("raw", ["", "soon", "-5", "1.5", "59", "0", " 120", "1_000"])
def test_interval_from_env_rejects_garbage(monkeypatch, raw):
    monkeypatch.setenv("STRATA_KB_CODE_SYNC_INTERVAL", raw)
    with pytest.raises(SystemExit) as exc:
        runner.interval_from_env()
    assert "STRATA_KB_CODE_SYNC_INTERVAL" in str(exc.value)


def test_run_command_once_exit_code_and_hub_kind(hub_with_drift):
    from typer.testing import CliRunner

    from strata_kb.cli import app

    root, c1 = hub_with_drift
    out = CliRunner().invoke(app, ["code-sync", "run", "--kb-dir", str(root / ".kb")])
    assert out.exit_code == 2, out.output
