from __future__ import annotations

from typer.testing import CliRunner

from strata_kb.autorun import switch
from strata_kb.cli import app
from strata_kb.config import load_config
from strata_kb.l3check import fixswitch

runner = CliRunner()


def _kb(tmp_path):
    kb = tmp_path / ".kb"
    kb.mkdir()
    return kb


def test_switch_default_off(tmp_path):
    kb = _kb(tmp_path)
    assert fixswitch.is_on(kb) is False


def test_turn_on_sets_flag_keeps_comments_and_gitignores(tmp_path):
    kb = _kb(tmp_path)
    (kb / "config.yaml").write_text("kind: child  # mine\n", encoding="utf-8")
    lines = fixswitch.turn_on(kb)
    text = (kb / "config.yaml").read_text(encoding="utf-8")
    assert "kind: child  # mine" in text and "l3_fix:\n  enabled: true" in text
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".kb-work/" in gitignore.splitlines()
    assert any(".gitignore" in line for line in lines)
    assert fixswitch.is_on(kb)


def test_turn_on_twice_does_not_duplicate_gitignore_line(tmp_path):
    kb = _kb(tmp_path)
    fixswitch.turn_on(kb)
    fixswitch.turn_on(kb)
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines.count(".kb-work/") == 1


def test_turn_on_keeps_existing_gitignore_lines(tmp_path):
    kb = _kb(tmp_path)
    (tmp_path / ".gitignore").write_text("dist\n.kb-work", encoding="utf-8")
    lines = fixswitch.turn_on(kb)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "dist\n.kb-work"
    assert not any(".gitignore" in line for line in lines)


def test_turn_on_appends_to_gitignore_without_trailing_newline(tmp_path):
    kb = _kb(tmp_path)
    (tmp_path / ".gitignore").write_text("dist", encoding="utf-8")
    fixswitch.turn_on(kb)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert text.splitlines() == ["dist", ".kb-work/"]


def test_turn_off(tmp_path):
    kb = _kb(tmp_path)
    fixswitch.turn_on(kb)
    fixswitch.turn_off(kb)
    assert fixswitch.is_on(kb) is False
    assert "l3_fix:\n  enabled: false" in (kb / "config.yaml").read_text(
        encoding="utf-8"
    )


def test_auto_switch_still_works(tmp_path):
    kb = _kb(tmp_path)
    switch.set_enabled(kb / "config.yaml", True)
    assert load_config(kb).auto.enabled is True
    assert load_config(kb).l3_fix.enabled is False


def test_cli_l3_fix_on_off(tmp_path):
    kb = _kb(tmp_path)
    result = runner.invoke(app, ["l3", "fix", "on", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert fixswitch.is_on(kb)
    result = runner.invoke(app, ["l3", "fix", "off", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert not fixswitch.is_on(kb)
