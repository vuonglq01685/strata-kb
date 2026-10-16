from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.autorun.switch import set_enabled, status, warnings_for_on
from strata_kb.cli import app
from strata_kb.config import AutoConfig, load_config

runner = CliRunner()


def _kb(tmp_path: Path, text: str) -> Path:
    (tmp_path / "config.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_set_enabled_edits_only_the_flag(tmp_path):
    kb = _kb(
        tmp_path, "kind: ba\n# keep me\nauto:\n  enabled: false\n  qa_interval: 120\n"
    )

    set_enabled(kb / "config.yaml", True)

    text = (kb / "config.yaml").read_text()
    assert "# keep me" in text and "qa_interval: 120" in text
    assert load_config(kb).auto.enabled is True
    assert load_config(kb).auto.qa_interval == 120


def test_set_enabled_off_round_trips(tmp_path):
    kb = _kb(tmp_path, "kind: dev\nauto:\n  enabled: true\n")
    set_enabled(kb / "config.yaml", False)
    assert load_config(kb).auto.enabled is False


def test_set_enabled_appends_block_when_absent(tmp_path):
    kb = _kb(tmp_path, "kind: ba\n# keep me")

    set_enabled(kb / "config.yaml", True)

    assert "# keep me" in (kb / "config.yaml").read_text()
    assert load_config(kb).auto.enabled is True


def test_set_enabled_adds_flag_to_block_lacking_it(tmp_path):
    kb = _kb(tmp_path, "kind: ba\nauto:\n  qa_interval: 120\nhub: x\n")

    set_enabled(kb / "config.yaml", True)

    cfg = load_config(kb)
    assert cfg.auto.enabled is True and cfg.auto.qa_interval == 120 and cfg.hub == "x"


def test_set_enabled_ignores_commented_block(tmp_path):
    kb = _kb(tmp_path, "kind: ba\n# auto:\n#   enabled: false\n")

    set_enabled(kb / "config.yaml", True)

    assert load_config(kb).auto.enabled is True


def test_set_enabled_creates_missing_file(tmp_path):
    set_enabled(tmp_path / "config.yaml", True)
    assert load_config(tmp_path).auto.enabled is True


def test_auto_config_defaults_off(tmp_path):
    _kb(tmp_path, "kind: ba\n")
    assert load_config(tmp_path).auto == AutoConfig()
    assert AutoConfig().qa_interval == 300
    assert AutoConfig().idle_interval == 600
    assert AutoConfig().hotfix_base == ""


def _registry(fed_hub: Path, entries: dict[str, str]) -> None:
    lines = ["repos:"] + [
        f"  {repo}: {{repo_id: {repo.split('/')[1]}, kind: {kind}}}"
        for repo, kind in entries.items()
    ]
    (fed_hub / "federation").mkdir(exist_ok=True)
    (fed_hub / "federation" / "registry.yaml").write_text("\n".join(lines) + "\n")


def test_warnings_mention_admin_merge_and_two_devs(tmp_path, fed_hub):
    _registry(fed_hub, {"o/dev-a": "dev", "o/dev-b": "dev", "o/ba": "ba"})

    warnings = warnings_for_on(_kb(tmp_path, "kind: dev\n"), str(fed_hub))

    assert any("admin" in w and "review" in w for w in warnings)
    assert any("one Dev" in w for w in warnings)


def test_warnings_one_dev_only_admin_line(tmp_path, fed_hub):
    _registry(fed_hub, {"o/dev-a": "dev", "o/ba": "ba"})
    warnings = warnings_for_on(_kb(tmp_path, "kind: dev\n"), str(fed_hub))
    assert len(warnings) == 1 and "admin" in warnings[0]


def test_warnings_unreachable_hub_says_registry_not_checked(tmp_path):
    warnings = warnings_for_on(_kb(tmp_path, "kind: dev\n"), "")
    assert any("registry not checked" in w for w in warnings)
    assert any("admin" in w for w in warnings)


def test_status_defaults_and_state_fields_none(tmp_path):
    _kb(tmp_path, "kind: ba\n")
    assert status(tmp_path) == {
        "enabled": False,
        "qa_interval": 300,
        "idle_interval": 600,
        "hotfix_base": "",
        "task": None,
        "attempts": None,
        "waiting_on": None,
        "stop_reason": None,
    }


def test_cli_auto_status_json(tmp_path):
    kb = _kb(tmp_path, "kind: ba\n")
    result = runner.invoke(app, ["auto", "status", "--json", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["enabled"] is False


def test_cli_auto_status_text(tmp_path):
    kb = _kb(tmp_path, "kind: ba\n")
    result = runner.invoke(app, ["auto", "status", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "enabled: False" in result.output.splitlines()


@pytest.mark.parametrize("kind", ["child", "hub", ""])
def test_cli_auto_on_refuses_outside_ba_dev(tmp_path, kind):
    kb = _kb(tmp_path, f"kind: {kind}\n" if kind else "hub: x\n")
    result = runner.invoke(app, ["auto", "on", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "ba" in result.output and "dev" in result.output
    assert load_config(kb).auto.enabled is False


def test_cli_auto_on_then_off(tmp_path, fed_hub):
    _registry(fed_hub, {"o/dev-a": "dev"})
    kb = _kb(tmp_path, "kind: dev\n")
    on = runner.invoke(app, ["auto", "on", "--hub", str(fed_hub), "--kb-dir", str(kb)])
    assert on.exit_code == 0, on.output
    assert "admin" in on.output
    assert on.output.rstrip().endswith("auto: on")
    assert load_config(kb).auto.enabled is True

    off = runner.invoke(app, ["auto", "off", "--kb-dir", str(kb)])
    assert off.exit_code == 0, off.output
    assert "auto: off" in off.output
    assert load_config(kb).auto.enabled is False


@pytest.mark.parametrize("on", [True, False])
def test_set_enabled_survives_column0_comment_in_block(tmp_path, on):
    kb = _kb(tmp_path, f"auto:\n# note\n  enabled: {str(not on).lower()}\n")

    set_enabled(kb / "config.yaml", on)

    text = (kb / "config.yaml").read_text()
    assert text.count("enabled:") == 1 and "# note" in text
    assert load_config(kb).auto.enabled is on


def test_set_enabled_keeps_inline_comment_on_flag_line(tmp_path):
    kb = _kb(tmp_path, "auto:\n  enabled: false  # keep\n  qa_interval: 5\n")

    set_enabled(kb / "config.yaml", True)

    assert "  enabled: true  # keep\n" in (kb / "config.yaml").read_text()


def test_set_enabled_refuses_when_flag_would_not_stick(tmp_path):
    original = "auto:\n  enabled: false\nauto:\n  enabled: false\n"
    kb = _kb(tmp_path, original)

    with pytest.raises(ValueError):
        set_enabled(kb / "config.yaml", True)

    assert (kb / "config.yaml").read_text() == original
