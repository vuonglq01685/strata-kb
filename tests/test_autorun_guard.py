import json

import pytest
from typer.testing import CliRunner

from strata_kb.autorun import claude, guard
from strata_kb.cli import app

AUTO = {claude.AUTO_TASK_ENV: "1"}
GOOD = [
    "AUTO-RESULT: done",
    "AUTO-RESULT: blocked-qa Q1,Q2",
    "AUTO-RESULT: blocked-split BUG-7",
    "AUTO-RESULT: blocked-review https://github.com/o/r/pull/3",
    "AUTO-RESULT: failed tests broke",
]


def test_guard_blocks_missing_line():
    out = guard.stop_decision({"last_assistant_message": "all done"}, AUTO)
    assert out is not None and out["decision"] == "block"
    assert all(form in out["reason"] for form in claude.RESULT_FORMS)


def test_guard_blocks_bad_line():
    out = guard.stop_decision({"last_assistant_message": "AUTO-RESULT: maybe"}, AUTO)
    assert out is not None and out["decision"] == "block"


@pytest.mark.parametrize("line", GOOD)
def test_guard_allows_valid_line(line):
    assert guard.stop_decision({"last_assistant_message": f"x\n{line}"}, AUTO) is None


def test_guard_never_blocks_when_stop_hook_active():
    payload = {"last_assistant_message": "nope", "stop_hook_active": True}
    assert guard.stop_decision(payload, AUTO) is None


def test_guard_silent_outside_auto():
    assert guard.stop_decision({"last_assistant_message": "nope"}, {}) is None


def test_guard_reads_transcript_when_no_last_message(tmp_path):
    def row(text):
        return {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": text}]},
        }

    path = tmp_path / "t.jsonl"
    path.write_text(
        "\n".join(json.dumps(r) for r in [row("AUTO-RESULT: done"), row("bye")])
    )
    out = guard.stop_decision({"transcript_path": str(path)}, AUTO)
    assert out is not None and out["decision"] == "block"
    path.write_text(json.dumps(row("hi\nAUTO-RESULT: done")))
    assert guard.stop_decision({"transcript_path": str(path)}, AUTO) is None


def test_cli_guard_stop_bad_json_exits_zero_silently(tmp_path):
    res = CliRunner().invoke(
        app,
        ["guard", "stop", "--hook-stdin", "--kb-dir", str(tmp_path / ".kb")],
        input="{",
        env=AUTO,
    )
    assert res.exit_code == 0 and res.stdout == ""
