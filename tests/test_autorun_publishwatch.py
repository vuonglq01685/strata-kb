"""publishwatch: a failed kb-publish run is re-run once, then stops the loop
(#140, second case) instead of reading as a hub that has not caught up."""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

import pytest

from strata_kb.autorun import publishwatch
from strata_kb.autorun import state as autostate
from strata_kb.ghio import GHError

FAILED_LOG = (
    "publish\tPublish snapshot\t2026-11-04T09:44:01.1Z intake rejected the publish "
    "(HTTP 502): push branch 'publish/myflix-ba' failed: remote: fatal error in "
    "commit_refs_rules\n"
    "publish\tPublish snapshot\t2026-11-04T09:44:01.2Z ##[error]Process completed "
    "with exit code 1.\n"
)


class FakeGh:
    def __init__(self, runs, jobs=None, log=FAILED_LOG, fail=False):
        self.runs, self.jobs, self.log, self.fail = runs, jobs, log, fail
        self.calls: list[tuple[str, ...]] = []

    def json(self, root, *args):
        self.calls.append(args)
        if self.fail:
            raise GHError("gh: not logged in")
        if args[:2] == ("run", "list"):
            return self.runs
        return {"jobs": self.jobs or []}

    def text(self, root, *args):
        self.calls.append(args)
        return self.log


def _run(conclusion="failure", status="completed", attempt=1, run_id=41809477611):
    return {
        "databaseId": run_id,
        "attempt": attempt,
        "status": status,
        "conclusion": conclusion,
        "url": f"https://github.com/o/r/actions/runs/{run_id}",
        "headBranch": "kb-publish/20261104-094300-5d7cd89",
    }


JOBS = [
    {
        "name": "publish",
        "conclusion": "failure",
        "steps": [
            {"name": "Build the plan", "conclusion": "success"},
            {"name": "Publish snapshot", "conclusion": "failure"},
        ],
    }
]


@pytest.fixture
def gh(monkeypatch):
    def install(fake: FakeGh) -> FakeGh:
        monkeypatch.setattr(publishwatch.ghio, "gh_available", lambda: True)
        monkeypatch.setattr(publishwatch.ghio, "run_json", fake.json)
        monkeypatch.setattr(publishwatch.ghio, "run_text", fake.text)
        return fake

    return install


def _check(tmp_path: Path):
    kb_dir = tmp_path / ".kb"
    return publishwatch.check(tmp_path, kb_dir, autostate.load(kb_dir)), kb_dir


def test_no_gh_checks_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(publishwatch.ghio, "gh_available", lambda: False)
    assert _check(tmp_path)[0] is None


@pytest.mark.parametrize("status", ["queued", "in_progress"])
def test_a_running_publish_is_left_to_finish(tmp_path, gh, status):
    gh(FakeGh([_run(conclusion="", status=status)]))
    assert _check(tmp_path)[0] is None


def test_no_publish_run_yet_checks_nothing(tmp_path, gh):
    gh(FakeGh([]))
    assert _check(tmp_path)[0] is None


def test_first_failure_is_logged_and_re_run_once(tmp_path, gh, caplog):
    fake = gh(FakeGh([_run()], jobs=JOBS))
    with caplog.at_level(logging.ERROR):
        outcome, kb_dir = _check(tmp_path)
    assert outcome == "idle"
    assert ("run", "rerun", "41809477611", "--failed") in fake.calls
    assert autostate.load(kb_dir).publish_retry == "41809477611:1"
    assert "publish / Publish snapshot" in caplog.text
    assert "fatal error in commit_refs_rules" in caplog.text
    assert "kb-publish/20261104-094300-5d7cd89" in caplog.text


def test_failed_re_run_stops_with_the_error(tmp_path, gh):
    gh(FakeGh([_run(attempt=2)], jobs=JOBS))
    kb_dir = tmp_path / ".kb"
    autostate.save(
        kb_dir, replace(autostate.load(kb_dir), publish_retry="41809477611:1")
    )
    outcome, _ = _check(tmp_path)
    assert outcome == "stopped"
    reason = autostate.load(kb_dir).stop_reason or ""
    assert reason.startswith("publish failed for kb-publish/20261104-094300-5d7cd89")
    assert "fatal error in commit_refs_rules" in reason


def test_re_run_that_never_started_stops(tmp_path, gh):
    fake = gh(FakeGh([_run(attempt=1)], jobs=JOBS))
    kb_dir = tmp_path / ".kb"
    autostate.save(
        kb_dir, replace(autostate.load(kb_dir), publish_retry="41809477611:1")
    )
    assert _check(tmp_path)[0] == "stopped"
    assert not any(c[:2] == ("run", "rerun") for c in fake.calls)


def test_success_clears_the_retry_mark(tmp_path, gh):
    gh(FakeGh([_run(conclusion="success", attempt=2)]))
    kb_dir = tmp_path / ".kb"
    autostate.save(
        kb_dir, replace(autostate.load(kb_dir), publish_retry="41809477611:1")
    )
    assert _check(tmp_path)[0] is None
    assert autostate.load(kb_dir).publish_retry is None


def test_gh_failure_is_a_warning_not_a_stop(tmp_path, gh, caplog):
    gh(FakeGh([], fail=True))
    with caplog.at_level(logging.WARNING):
        assert _check(tmp_path)[0] is None
    assert "kb-publish runs not read" in caplog.text


def test_ba_loop_stops_on_a_failed_re_run_before_picking(tmp_path, gh, monkeypatch):
    from strata_kb import planstatus
    from strata_kb.autorun import picker, runner
    from strata_kb.config import AutoConfig, KBConfig
    from strata_kb.hub import HubHandle
    from strata_kb.missionnext import StoryStatus

    monkeypatch.setattr(runner, "_publish_check", publishwatch.check)
    story = StoryStatus("US9", "M-x", "t", "to-draft", ())
    monkeypatch.setattr(
        planstatus, "next_from_hub", lambda h, repo=None: ([story], [], [])
    )
    picked: list[int] = []
    monkeypatch.setattr(picker, "pick_ba", lambda *a, **k: picked.append(1))
    gh(FakeGh([_run(attempt=2)], jobs=JOBS))
    kb_dir = tmp_path / ".kb"
    autostate.save(
        kb_dir, replace(autostate.load(kb_dir), publish_retry="41809477611:1")
    )

    class Qa:
        def list(self, status="open", repo="", ticket=""):
            return []

    outcome = runner.run_once(
        tmp_path,
        kb_dir,
        cfg=KBConfig(
            kind="ba", repo_id="ba", intake="http://i", auto=AutoConfig(enabled=True)
        ),
        hub=HubHandle(root=tmp_path),
        qa=Qa(),
        run_task=lambda *a, **k: None,
    )
    assert outcome == "stopped"
    assert picked == []  # never waited on, never skipped
    runner.resume(kb_dir)
    assert autostate.load(kb_dir).publish_retry is None  # a resume retries again


def test_a_cancelled_run_counts_as_failed(tmp_path, gh):
    fake = gh(FakeGh([_run(conclusion="cancelled")], jobs=JOBS))
    assert _check(tmp_path)[0] == "idle"
    assert ("run", "rerun", "41809477611", "--failed") in fake.calls


def test_a_skipped_run_does_not_hide_the_failure_before_it(tmp_path, gh):
    runs = [_run(conclusion="skipped", run_id=2), _run(run_id=1)]
    fake = gh(FakeGh(runs, jobs=JOBS))
    assert _check(tmp_path)[0] == "idle"
    assert ("run", "rerun", "1", "--failed") in fake.calls


def test_a_newer_run_gets_its_own_re_run(tmp_path, gh):
    # The mark is an older run's: the newer merge's first failure is re-run,
    # not taken for a failed re-run.
    fake = gh(FakeGh([_run(run_id=2)], jobs=JOBS))
    kb_dir = tmp_path / ".kb"
    autostate.save(kb_dir, replace(autostate.load(kb_dir), publish_retry="1:1"))
    assert _check(tmp_path)[0] == "idle"
    assert ("run", "rerun", "2", "--failed") in fake.calls
    assert autostate.load(kb_dir).publish_retry == "2:1"


def test_unexpected_gh_json_is_a_warning(tmp_path, gh, caplog):
    gh(FakeGh([{"status": "completed"}]))
    with caplog.at_level(logging.WARNING):
        assert _check(tmp_path)[0] is None
    assert "kb-publish runs not read" in caplog.text
