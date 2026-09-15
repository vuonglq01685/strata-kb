import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.usage import ledger
from tests.test_usage_transcript import usage_row, user_row, write_transcript

runner = CliRunner()


def kb_dir(tmp_path: Path, kind: str = "ba") -> Path:
    d = tmp_path / ".kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(
        yaml.safe_dump({"kind": kind, "repo_id": "KS-BA"}), encoding="utf-8"
    )
    return d


def test_ingest_writes_the_ledger_and_reports_counts(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    result = runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "1" in result.output
    rows = ledger.read_rows(d)
    assert [(r.uuid, r.ticket, r.actor) for r in rows] == [
        ("a1", "open-new-flight", "ba")
    ]


def test_ingest_is_idempotent(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert len(ledger.read_rows(d)) == 1


def test_ingest_takes_the_actor_from_the_config_kind(tmp_path: Path):
    d = kb_dir(tmp_path, kind="dev")
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert ledger.read_rows(d)[0].actor == "dev"


def test_ingest_with_no_kind_records_an_unknown_actor(tmp_path: Path):
    d = tmp_path / ".kb"
    d.mkdir()
    t = write_transcript(tmp_path, [usage_row("a1")])

    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    assert ledger.read_rows(d)[0].actor == "unknown"


def test_ingest_forced_ticket_wins(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )

    runner.invoke(
        app,
        ["usage", "ingest-transcript", str(t), "--ticket", "ATM-7", "--kb-dir", str(d)],
    )

    assert ledger.read_rows(d)[0].ticket == "ATM-7"


def test_ticket_flag_against_an_already_ingested_transcript_explains_the_dead_end(
    tmp_path: Path,
):
    # Global uuid dedup (I2) + --ticket compose into a dead escape hatch once
    # the Stop hook has already ingested a transcript: exit 0 + "already
    # recorded" must not read as success without saying why --ticket did
    # nothing and what to do instead.
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(
        app,
        ["usage", "ingest-transcript", str(t), "--ticket", "open-new-flight",
         "--kb-dir", str(d)],
    )

    assert result.exit_code == 0, result.output
    assert "already recorded" in result.output
    assert "--ticket" in result.output
    assert "cannot move" in result.output
    assert ".jsonl" in result.output


def test_hook_mode_log_includes_the_raw_payload_snippet(tmp_path: Path):
    # Three different failures (bad JSON, empty stdin, clobbered stdin) must
    # not log identically apart from the timestamp — the raw payload snippet
    # is what tells a human which one actually happened.
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input="<<<clobbered>>>",
    )

    assert result.exit_code == 0, result.output
    log = (d / "usage" / "ingest-errors.log").read_text(encoding="utf-8")
    assert "<<<clobbered>>>" in log


def test_hook_mode_skips_a_kb_dir_with_no_config_and_writes_no_ledger(tmp_path: Path):
    # A missing .kb/config.yaml is strong evidence this is the wrong
    # directory — kb init always creates one — so the hook must not create a
    # ghost ledger wherever the process happens to be started from.
    d = tmp_path / "frontend" / ".kb"
    t = write_transcript(tmp_path, [usage_row("a1")])
    payload = json.dumps({"transcript_path": str(t)})

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert not (d / "usage").exists()


def test_report_over_a_corrupt_ledger_exits_one_with_a_message_not_a_traceback(
    tmp_path: Path,
):
    d = kb_dir(tmp_path)
    usage_dir = d / "usage"
    usage_dir.mkdir(parents=True)
    (usage_dir / "open-new-flight.jsonl").write_text('{"uuid": "x"}\n', encoding="utf-8")

    result = runner.invoke(app, ["usage", "report", "--kb-dir", str(d)])

    assert result.exit_code == 1
    assert "open-new-flight.jsonl" in result.output
    assert "Traceback" not in result.output


def test_ingest_without_a_path_or_hook_stdin_is_a_usage_error(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(app, ["usage", "ingest-transcript", "--kb-dir", str(d)])

    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_hook_mode_reads_the_transcript_path_from_stdin(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])
    payload = json.dumps(
        {"session_id": "sess-1", "transcript_path": str(t), "cwd": str(tmp_path)}
    )

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert result.output == ""  # the hook's stdout would land in the session
    assert len(ledger.read_rows(d)) == 1


def test_hook_mode_exits_zero_on_garbage_stdin_and_logs_it(tmp_path: Path):
    # A Stop hook exiting non-zero blocks Claude from ending its turn. An
    # ingest failure must never be able to freeze a session.
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input="not json at all",
    )

    assert result.exit_code == 0, result.output
    log = (d / "usage" / "ingest-errors.log").read_text(encoding="utf-8")
    assert "not json" in log or "JSON" in log


def test_hook_mode_exits_zero_when_the_transcript_is_missing(tmp_path: Path):
    d = kb_dir(tmp_path)
    payload = json.dumps({"transcript_path": str(tmp_path / "nope.jsonl")})

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert (d / "usage" / "ingest-errors.log").exists()


def test_hook_mode_exits_zero_when_the_configured_kind_is_invalid(tmp_path: Path):
    # kind: is a 5-value Literal; a hand-typed value outside it (e.g. "qa")
    # makes config.load_config raise pydantic.ValidationError. Unguarded, that
    # would fail this hook on every turn, forever, with no log entry to
    # diagnose it from.
    d = tmp_path / ".kb"
    d.mkdir()
    (d / "config.yaml").write_text(yaml.safe_dump({"kind": "qa"}), encoding="utf-8")
    t = write_transcript(tmp_path, [usage_row("a1")])
    payload = json.dumps({"transcript_path": str(t)})

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert (d / "usage" / "ingest-errors.log").exists()


def test_hook_mode_exits_zero_when_the_ledger_is_corrupt(tmp_path: Path):
    # A ledger truncated by a crash mid-append raises json.JSONDecodeError out
    # of ledger._existing_uuids; that must not surface as an uncaught hook
    # failure either.
    d = kb_dir(tmp_path)
    usage_dir = d / "usage"
    usage_dir.mkdir(parents=True)
    (usage_dir / "_unattributed.jsonl").write_text('{"uuid": "broke\n', encoding="utf-8")
    t = write_transcript(tmp_path, [usage_row("a1")])
    payload = json.dumps({"transcript_path": str(t)})

    result = runner.invoke(
        app, ["usage", "ingest-transcript", "--hook-stdin", "--kb-dir", str(d)],
        input=payload,
    )

    assert result.exit_code == 0, result.output
    assert result.output == ""
    assert (usage_dir / "ingest-errors.log").exists()


def test_ingest_reports_a_missing_transcript_without_hook_stdin(tmp_path: Path):
    # The non-hook error path had no test at all: nothing invoked a non-hook
    # failure, so the secho + Exit(1) branch was uncovered.
    d = kb_dir(tmp_path)
    missing = tmp_path / "nope.jsonl"

    result = runner.invoke(
        app, ["usage", "ingest-transcript", str(missing), "--kb-dir", str(d)]
    )

    assert result.exit_code == 1
    assert result.output.strip() != ""
    assert ledger.read_rows(d) == []


def test_note_appends_a_row_by_hand(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "10", "--tokens-out", "20",
         "--assistant", "copilot", "--kb-dir", str(d)],
    )

    assert result.exit_code == 0, result.output
    (row,) = ledger.read_rows(d)
    assert (row.ticket, row.phase, row.tokens_out, row.est) == ("ATM-7", "dev-plan", 20, True)


def test_note_est_marks_the_row_as_an_estimate(tmp_path: Path):
    d = kb_dir(tmp_path)

    runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--est", "--assistant", "copilot", "--kb-dir", str(d)],
    )

    (row,) = ledger.read_rows(d)
    assert (row.est, row.assistant) == (True, "copilot")


def test_note_refuses_an_unusable_ticket_id(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "../escape", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--assistant", "copilot", "--kb-dir", str(d)],
    )

    assert result.exit_code == 1
    assert "ticket id" in result.output


def test_note_rejects_a_negative_token_count(tmp_path: Path):
    # note is the one path where a human types the numbers; a typo'd negative
    # value must not silently subtract from the reported spend.
    d = kb_dir(tmp_path)

    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "-5", "--tokens-out", "20",
         "--kb-dir", str(d)],
    )

    assert result.exit_code != 0
    assert ledger.read_rows(d) == []


def test_note_requires_an_assistant(tmp_path: Path):
    d = kb_dir(tmp_path)
    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--kb-dir", str(d)],
    )
    assert result.exit_code != 0
    assert "--assistant" in result.output


def test_note_measured_overrides_the_estimate_default(tmp_path: Path):
    d = kb_dir(tmp_path)
    runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--measured", "--assistant", "cursor", "--kb-dir", str(d)],
    )
    (row,) = ledger.read_rows(d)
    assert (row.est, row.assistant) == (False, "cursor")


def test_report_writes_a_self_contained_html_file(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")]
    )
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(app, ["usage", "report", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    html = (d / "usage" / "report.html").read_text(encoding="utf-8")
    assert "open-new-flight" in html
    assert "<script" not in html.lower()


def test_report_md_prints_to_stdout_and_writes_nothing(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [usage_row("a1")])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert result.output.lstrip().startswith("| ")
    assert not (d / "usage" / "report.html").exists()


def test_report_ticket_filter_keeps_only_that_ticket(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(
        tmp_path,
        [
            user_row("tickets/open-new-flight.md"), usage_row("a1"),
            user_row("tickets/ATM-7.md"), usage_row("a2"),
        ],
    )
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])

    result = runner.invoke(
        app, ["usage", "report", "--ticket", "ATM-7", "--json", "--kb-dir", str(d)]
    )

    data = json.loads(result.output)
    assert [b["key"] for b in data["by_ticket"]] == ["ATM-7"]


def test_report_on_an_empty_ledger_says_so_and_exits_zero(tmp_path: Path):
    d = kb_dir(tmp_path)

    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    assert "no usage" in result.output.lower()


def test_report_json_on_an_empty_ledger_is_still_valid_json(tmp_path: Path):
    # --json is the machine surface a PR/CI step consumes, and every repo
    # starts in this state before its first ingest — it must stay parseable.
    d = kb_dir(tmp_path)

    result = runner.invoke(app, ["usage", "report", "--json", "--kb-dir", str(d)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["total"]["rows"] == 0


def test_report_footer_counts_hook_errors(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])
    (d / "usage" / "ingest-errors.log").write_text("t1 boom\nt2 bang\n", encoding="utf-8")

    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])

    assert "2 hook ingest error(s) logged" in result.output
    as_json = json.loads(runner.invoke(app, ["usage", "report", "--json", "--kb-dir", str(d)]).output)
    assert as_json["hook_errors"] == 2
