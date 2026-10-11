"""`kb usage report --with` and `--summary` (1.16.0, review B4): price one
ticket across the BA and Dev ledgers, and print the short PR-body block."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.usage import ledger
from strata_kb.usage.ledger import UsageRow
from tests.test_cli_usage import kb_dir

runner = CliRunner()


def _row(uuid: str, *, actor: str, phase: str, ticket: str = "T-7", out: int = 100):
    return UsageRow(
        uuid=uuid,
        ts="2026-10-10T09:00:00Z",
        session=f"sess-{actor}",
        actor=actor,
        phase=phase,
        ticket=ticket,
        model="claude-sonnet-5",
        tokens_in=10,
        tokens_out=out,
        cache_read=0,
        cache_write_5m=0,
        cache_write_1h=0,
        sidechain=False,
        branch=None,
        assistant="claude-code",
        est=False,
    )


def _two_repos(tmp_path: Path) -> tuple[Path, Path]:
    ba = kb_dir(tmp_path / "ba", kind="ba")
    dev = kb_dir(tmp_path / "dev", kind="dev")
    ledger.append_rows(
        ba,
        [
            _row("b1", actor="ba", phase="ba-ticket-author"),
            _row("b2", actor="ba", phase="sa-ticket-ground"),
            _row("b3", actor="ba", phase="ba-ticket-author", ticket="T-8"),
        ],
    )
    ledger.append_rows(
        dev,
        [
            _row("d1", actor="dev", phase="dev-plan"),
            _row("d2", actor="dev", phase="dev-execute", out=900),
        ],
    )
    return ba, dev


def test_read_rows_from_merges_and_dedupes(tmp_path: Path):
    ba, dev = _two_repos(tmp_path)
    rows = ledger.read_rows_from([dev, ba, ba])  # ba named twice
    assert sorted(r.uuid for r in rows) == ["b1", "b2", "b3", "d1", "d2"]


def test_with_prices_one_ticket_across_both_repos(tmp_path: Path):
    ba, dev = _two_repos(tmp_path)
    args = ["usage", "report", "--ticket", "T-7", "--json", "--kb-dir", str(dev)]
    alone = runner.invoke(app, args)
    merged = runner.invoke(app, [*args, "--with", str(ba)])
    assert alone.exit_code == merged.exit_code == 0, merged.output
    assert '"rows": 2' in alone.output.split('"by_ticket"')[0]
    assert '"rows": 4' in merged.output.split('"by_ticket"')[0]
    for phase in ("ba-ticket-author", "sa-ticket-ground", "dev-plan", "dev-execute"):
        assert phase in merged.output


def test_with_writes_nothing(tmp_path: Path):
    ba, dev = _two_repos(tmp_path)
    before = sorted(p.read_bytes() for p in (dev / "usage").glob("*.jsonl"))
    runner.invoke(
        app, ["usage", "report", "--md", "--kb-dir", str(dev), "--with", str(ba)]
    )
    after = sorted(p.read_bytes() for p in (dev / "usage").glob("*.jsonl"))
    assert before == after


def test_summary_is_a_short_usage_block(tmp_path: Path):
    ba, dev = _two_repos(tmp_path)
    result = runner.invoke(
        app,
        [
            "usage",
            "report",
            "--ticket",
            "T-7",
            "--summary",
            "--kb-dir",
            str(dev),
            "--with",
            str(ba),
        ],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "## Usage"
    assert lines[2].startswith("Total for T-7: 4 calls,")
    assert len(lines) <= 3 + 3 + 6 + 1  # heading, total, table head, phases, rest
    # costliest phase first
    phase_rows = [
        line
        for line in lines
        if line.startswith("| dev-")
        or line.startswith("| ba-")
        or line.startswith("| sa-")
    ]
    assert phase_rows[0].startswith("| dev-execute ")


def test_summary_caps_the_phase_rows(tmp_path: Path):
    dev = kb_dir(tmp_path / "dev", kind="dev")
    ledger.append_rows(
        dev, [_row(f"r{i}", actor="dev", phase=f"phase-{i}") for i in range(9)]
    )
    result = runner.invoke(
        app, ["usage", "report", "--ticket", "T-7", "--summary", "--kb-dir", str(dev)]
    )
    assert result.output.count("| phase-") == 6
    assert "| 3 more phase(s) |" in result.output
