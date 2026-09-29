"""`kb ticket tidy` — flat tickets/*.md into tickets/<mission-id>/."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from strata_kb import tickettidy
from strata_kb.cli import app

runner = CliRunner()

PARENTED = "# Story\n> Parent mission: M-platform\n\n## Summary\nx\n"
ORPHAN = "# Story\n\n## Summary\nx\n"


def _tickets(tmp_path: Path) -> Path:
    d = tmp_path / "tickets"
    d.mkdir()
    (d / "M-platform-US1.md").write_text(PARENTED, encoding="utf-8")
    (d / "M-platform-US2.md").write_text(PARENTED, encoding="utf-8")
    (d / "legacy-login.md").write_text(ORPHAN, encoding="utf-8")
    return d


def test_plan_moves_parented_files_and_lists_orphans(tmp_path):
    d = _tickets(tmp_path)
    moves, unsorted, notes = tickettidy.plan_moves(d)
    assert moves == [
        (d / "M-platform-US1.md", d / "M-platform" / "M-platform-US1.md"),
        (d / "M-platform-US2.md", d / "M-platform" / "M-platform-US2.md"),
    ]
    assert unsorted == [d / "legacy-login.md"]
    assert notes == []


def test_plan_moves_ignores_files_already_in_folders_and_bad_ids(tmp_path):
    d = _tickets(tmp_path)
    (d / "M-platform").mkdir()
    (d / "M-platform" / "M-platform-US3.md").write_text(PARENTED, encoding="utf-8")
    (d / "bad.md").write_text("# S\n> Parent mission: Not_An_Id\n", encoding="utf-8")
    moves, unsorted, _notes = tickettidy.plan_moves(d)
    assert all(src.parent == d for src, _dst in moves)
    assert d / "bad.md" in unsorted


def test_apply_moves_creates_folders_and_refuses_to_overwrite(tmp_path):
    d = _tickets(tmp_path)
    (d / "M-platform").mkdir()
    (d / "M-platform" / "M-platform-US2.md").write_text("other", encoding="utf-8")
    moves, _u, _n = tickettidy.plan_moves(d)
    done, conflicts = tickettidy.apply_moves(moves)
    assert done == [(d / "M-platform-US1.md", d / "M-platform" / "M-platform-US1.md")]
    assert (d / "M-platform" / "M-platform-US1.md").read_text(encoding="utf-8") == PARENTED
    assert (d / "M-platform-US2.md").exists()
    assert conflicts == [f"conflict: {d / 'M-platform' / 'M-platform-US2.md'} already exists — left {d / 'M-platform-US2.md'} in place"]


def test_cli_tidy_moves_reports_and_is_idempotent(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d)])
    assert result.exit_code == 0, result.output
    assert f"moved: {d / 'M-platform-US1.md'} → {d / 'M-platform' / 'M-platform-US1.md'}" in result.output
    assert f"unsorted: {d / 'legacy-login.md'} — pass --into <folder>" in result.output
    again = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d)])
    assert again.exit_code == 0
    assert "moved:" not in again.output
    assert "unsorted:" in again.output


def test_cli_tidy_into_moves_the_named_files(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, [
        "ticket", "tidy", "--tickets-dir", str(d), "--into", "epic-login", str(d / "legacy-login.md"),
    ])
    assert result.exit_code == 0, result.output
    assert (d / "epic-login" / "legacy-login.md").is_file()
    assert "unsorted:" not in result.output


def test_cli_tidy_into_rejects_a_bad_folder_name(tmp_path):
    d = _tickets(tmp_path)
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(d), "--into", "../x", str(d / "legacy-login.md")])
    assert result.exit_code == 1
    assert "--into" in result.output


def test_cli_tidy_missing_dir_is_a_red_line(tmp_path):
    result = runner.invoke(app, ["ticket", "tidy", "--tickets-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
