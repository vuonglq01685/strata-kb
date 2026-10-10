from pathlib import Path

from strata_kb.usage import ingest, ledger
from tests.test_cli_usage import kb_dir
from tests.test_usage_transcript import usage_row, user_row, write_transcript


def _session(tmp_path: Path) -> Path:
    main = write_transcript(tmp_path, [user_row("tickets/ATM-7.md"), usage_row("m1")],
                            name="sess-1.jsonl")
    folder = tmp_path / "sess-1" / "subagents"
    folder.mkdir(parents=True)
    write_transcript(folder, [usage_row("s1", requestId="r1"), usage_row("s2", requestId="r2")],
                     name="agent-a.jsonl")
    return main


def test_a_main_ingest_sweeps_subagents_and_holds_back_their_last_call(tmp_path: Path):
    d = kb_dir(tmp_path)
    result = ingest.ingest_main(d, _session(tmp_path), actor="dev", hold_back_subagents=True)
    assert sorted(r.uuid for r in ledger.read_rows(d)) == ["m1", "s1"]
    assert result.report.written == 2


def test_subagent_stop_then_picks_up_the_held_back_call_without_duplicates(tmp_path: Path):
    d = kb_dir(tmp_path)
    main = _session(tmp_path)
    ingest.ingest_main(d, main, actor="dev", hold_back_subagents=True)
    sub = tmp_path / "sess-1" / "subagents" / "agent-a.jsonl"
    result = ingest.ingest_subagent(d, sub, parent=main, actor="dev")
    assert (result.report.written, result.report.duplicates) == (1, 1)
    rows = {r.uuid: r for r in ledger.read_rows(d)}
    assert rows["s2"].sidechain and rows["s2"].ticket == "ATM-7"


def test_an_unreadable_parent_still_ingests_the_subagent_and_says_so(tmp_path: Path):
    d = kb_dir(tmp_path)
    sub = write_transcript(tmp_path, [usage_row("s1")], name="agent-x.jsonl")
    result = ingest.ingest_subagent(d, sub, parent=tmp_path / "missing.jsonl", actor="dev")
    assert result.report.written == 1
    assert result.notes and "missing.jsonl" in result.notes[0]


def test_a_manual_path_under_subagents_finds_its_parent(tmp_path: Path):
    d = kb_dir(tmp_path)
    _session(tmp_path)
    ingest.ingest_path(d, tmp_path / "sess-1" / "subagents" / "agent-a.jsonl", actor="dev")
    assert {r.ticket for r in ledger.read_rows(d)} == {"ATM-7"}


def test_a_manual_main_ingest_does_not_hold_back(tmp_path: Path):
    d = kb_dir(tmp_path)
    ingest.ingest_path(d, _session(tmp_path), actor="dev")
    assert sorted(r.uuid for r in ledger.read_rows(d)) == ["m1", "s1", "s2"]


def test_one_unreadable_subagent_file_does_not_stop_the_sweep(tmp_path: Path):
    d = kb_dir(tmp_path)
    main = _session(tmp_path)
    # Sorts before agent-a.jsonl and matches the glob, but reading it fails
    # (IsADirectoryError, an OSError) — as a file deleted mid-sweep would.
    (tmp_path / "sess-1" / "subagents" / "agent-0.jsonl").mkdir()
    result = ingest.ingest_main(d, main, actor="dev", hold_back_subagents=False)
    assert sorted(r.uuid for r in ledger.read_rows(d)) == ["m1", "s1", "s2"]
    assert len(result.notes) == 1 and "agent-0.jsonl" in result.notes[0]
