from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from strata_kb.autorun.claude import TaskResult, parse_result, prompt_for, run_task
from tests.cli_stub import write_cli_stub

FAKE = Path(__file__).with_name("fake_claude.py")


class FakeClaude:
    def __init__(self, bindir: Path, replies: Path) -> None:
        self.replies = replies
        self.bindir = bindir

    def script(self, *entries) -> None:
        self.replies.write_text(json.dumps(list(entries)), encoding="utf-8")

    def calls(self) -> list[dict]:
        path = Path(str(self.replies) + ".calls")
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        return [json.loads(line) for line in lines]


@pytest.fixture
def fake_claude(tmp_path, monkeypatch) -> FakeClaude:
    bindir = tmp_path / "bin"
    write_cli_stub(bindir, "claude", FAKE.read_text(encoding="utf-8"))
    replies = tmp_path / "replies.json"
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_REPLIES", str(replies))
    return FakeClaude(bindir, replies)


def test_parse_done():
    assert parse_result("...\nAUTO-RESULT: done\n").kind == "done"


def test_parse_blocked_ids():
    assert parse_result("AUTO-RESULT: blocked-qa Q12,Q13").ids == (12, 13)


def test_missing_line_is_failed():
    assert parse_result("done!\n") == TaskResult("failed", (), "no result line")


def test_trailing_chatter_after_line_is_failed():
    assert parse_result("AUTO-RESULT: done\nAlso note...").kind == "failed"


@pytest.mark.parametrize(
    "line",
    [
        "AUTO-RESULT: blocked-qa",
        "AUTO-RESULT: blocked-qa Q1,x",
        "AUTO-RESULT: maybe",
        "AUTO-RESULT: usage-limit",
    ],
)
def test_malformed_line_is_failed(line):
    assert parse_result(line).kind == "failed"


# --- prompt_for --------------------------------------------------------------


def test_prompt_for_names_skill_and_all_three_forms():
    prompt = prompt_for("dev-implement", "US3", "code")
    assert prompt.splitlines()[0] == "/dev-implement US3"
    assert prompt.splitlines()[1] == ""
    assert "code repo" in prompt
    for form in (
        "AUTO-RESULT: done",
        "AUTO-RESULT: blocked-qa Q",
        "AUTO-RESULT: failed",
    ):
        assert form in prompt


def test_prompt_for_strips_empty_arg():
    assert prompt_for("ba-next", "", "docs").splitlines()[0] == "/ba-next"


# --- run_task ----------------------------------------------------------------


def test_run_task_fresh_process_and_log(fake_claude, tmp_path):
    fake_claude.script("work\nAUTO-RESULT: done", "work\nAUTO-RESULT: blocked-qa Q7")
    root = tmp_path / "repo"
    root.mkdir()
    logs = tmp_path / "logs"
    prompt = "/dev-implement US3\n\nbody"

    first = run_task(root, prompt, log_dir=logs)
    second = run_task(root, prompt, log_dir=logs)

    assert (first.kind, second.kind, second.ids) == ("done", "blocked-qa", (7,))
    calls = fake_claude.calls()
    assert len(calls) == 2  # one process per task
    assert calls[0]["argv"] == [
        "-p",
        "--output-format",
        "json",
        "--permission-mode",
        "acceptEdits",
    ]
    assert Path(calls[0]["cwd"]).resolve() == root.resolve()
    assert calls[0]["stdin"] == prompt
    assert calls[0]["auto_task"] == "1"  # kb auto on|off|run refuse under it
    # Same-second runs get a -2 suffix, which sorts before ".log"; so match
    # by content, not by order.
    texts = [
        p.read_text(encoding="utf-8") for p in logs.glob("*-dev-implement-US3*.log")
    ]
    assert len(texts) == 2
    log = next(t for t in texts if "AUTO-RESULT: done" in t)
    assert any("blocked-qa Q7" in t for t in texts)
    for part in ("PROMPT", "STDOUT", "STDERR", prompt, "AUTO-RESULT: done"):
        assert part in log
    assert log.rstrip().splitlines()[-1].startswith("exit=0 duration=")


def test_usage_limit_envelope(fake_claude, tmp_path):
    fake_claude.script({"is_error": True, "result": "You've hit your usage limit"})
    result = run_task(tmp_path, "/x", log_dir=tmp_path / "logs")
    assert result == TaskResult(
        "usage-limit", (), "claude: You've hit your usage limit"
    )


def test_usage_limit_nonzero_exit(fake_claude, tmp_path):
    fake_claude.script({"_exit": 1, "_stderr": "5-hour LIMIT reached"})
    result = run_task(tmp_path, "/x", log_dir=tmp_path / "logs")
    assert result.kind == "usage-limit"
    assert "LIMIT reached" in result.reason


def test_non_usage_limit_error_is_failed(fake_claude, tmp_path):
    fake_claude.script({"is_error": True, "result": "file size limit"})
    assert run_task(tmp_path, "/x", log_dir=tmp_path / "logs").kind == "failed"


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("You've hit your usage limit", "usage-limit"),
        ("You've hit your limit \u00b7 resets 3pm", "usage-limit"),
        ("Weekly limit reached, resets Monday", "usage-limit"),
        ("Context limit reached", "failed"),
        ("file size limit", "failed"),
    ],
)
def test_usage_limit_wording(fake_claude, tmp_path, message, kind):
    fake_claude.script({"is_error": True, "result": message})
    assert run_task(tmp_path, "/x", log_dir=tmp_path / "logs").kind == kind


def test_other_error_is_failed_and_capped(fake_claude, tmp_path):
    fake_claude.script({"is_error": True, "result": "boom " * 400})
    result = run_task(tmp_path, "/x", log_dir=tmp_path / "logs")
    assert result.kind == "failed" and result.reason.startswith("claude: boom")
    assert len(result.reason) <= 500


def test_nonzero_exit_without_envelope_is_failed(fake_claude, tmp_path):
    fake_claude.script({"_exit": 2, "_stderr": "crash"})
    result = run_task(tmp_path, "/x", log_dir=tmp_path / "logs")
    assert result.kind == "failed" and "crash" in result.reason


def test_reply_without_result_line_is_failed(fake_claude, tmp_path):
    fake_claude.script("all good")
    assert run_task(tmp_path, "/x", log_dir=tmp_path / "logs") == TaskResult(
        "failed", (), "no result line"
    )


def test_timeout_is_failed(tmp_path, monkeypatch):
    import subprocess

    from strata_kb.autorun import claude

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 5)

    monkeypatch.setattr(claude.subprocess, "run", boom)
    result = run_task(tmp_path, "/x", log_dir=tmp_path / "logs", timeout=5)
    assert result == TaskResult("failed", (), "timed out after 5s")
    assert list((tmp_path / "logs").glob("*.log"))


def test_missing_executable_is_failed(tmp_path):
    result = run_task(
        tmp_path, "/x", log_dir=tmp_path / "logs", executable=str(tmp_path / "nope")
    )
    assert result.kind == "failed"
