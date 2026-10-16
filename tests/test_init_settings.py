"""`kb init` scaffolds an auto-mode permission allowlist into
.claude/settings.json for ba/dev, merging into (never replacing) an existing file."""

import json
from pathlib import Path

import pytest

from strata_kb import conventions
from strata_kb.initcmd import (
    TEST_COMMANDS,
    expected_files,
    init_repo,
    merge_settings,
    read_template,
)

USAGE_CMD = "kb usage ingest-transcript --hook-stdin"


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude" / "settings.json").read_text("utf-8"))


def _commands(settings: dict, event: str) -> list[str]:
    return [
        hook["command"] for group in settings["hooks"][event] for hook in group["hooks"]
    ]


@pytest.mark.parametrize("kind", ["ba", "dev"])
def test_fresh_repo_gets_allow_deny_and_usage_hooks(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)

    settings = _settings(tmp_path)

    assert "Bash(kb *)" in settings["permissions"]["allow"]
    assert "mcp__strata-kb__*" in settings["permissions"]["allow"]
    assert "Bash(git push --force*)" in settings["permissions"]["deny"]
    assert "Edit(.claude/settings.json)" in settings["permissions"]["deny"]
    for event in ("Stop", "SubagentStop"):
        assert _commands(settings, event) == [USAGE_CMD]


@pytest.mark.parametrize("kind", ["ba", "dev"])
def test_template_never_grants_bypass(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    text = (tmp_path / ".claude" / "settings.json").read_text("utf-8")
    assert "bypassPermissions" not in text
    assert "dangerously" not in text


def test_hub_and_child_still_get_the_usage_hooks_template_only(tmp_path: Path):
    for kind in ("hub", "child"):
        assert ".claude/settings.json" not in expected_files(kind), kind


def test_existing_allow_is_kept_and_template_entries_are_added(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"permissions": {"allow": ["Bash(make *)"]}, "model": "x"}),
        encoding="utf-8",
    )

    report = init_repo(tmp_path, "dev")

    settings = _settings(tmp_path)
    allow = settings["permissions"]["allow"]
    assert allow[0] == "Bash(make *)"  # existing first
    assert "Bash(kb *)" in allow
    assert settings["model"] == "x"
    assert ".claude/settings.json" in report.updated


def test_hooks_are_not_duplicated_on_a_second_init(tmp_path: Path):
    init_repo(tmp_path, "dev")
    first = (tmp_path / ".claude" / "settings.json").read_text("utf-8")

    report = init_repo(tmp_path, "dev")

    assert (tmp_path / ".claude" / "settings.json").read_text("utf-8") == first
    assert ".claude/settings.json" in report.skipped
    assert _commands(_settings(tmp_path), "Stop") == [USAGE_CMD]


def test_existing_other_hook_is_kept_and_usage_hook_added(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    own = {"hooks": [{"type": "command", "command": "echo mine"}]}
    path.write_text(json.dumps({"hooks": {"Stop": [own]}}), encoding="utf-8")

    init_repo(tmp_path, "ba")

    assert _commands(_settings(tmp_path), "Stop") == ["echo mine", USAGE_CMD]


def test_invalid_json_is_left_alone_with_a_note(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")

    report = init_repo(tmp_path, "dev")

    assert path.read_text("utf-8") == "{not json"
    assert any("settings.json" in n for n in report.notes)


def test_unexpected_shape_is_left_alone_with_a_note(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"permissions": {"allow": "Bash(make *)"}}', encoding="utf-8")

    report = init_repo(tmp_path, "dev")

    assert path.read_text("utf-8") == '{"permissions": {"allow": "Bash(make *)"}}'
    assert any("settings.json" in n for n in report.notes)


def test_force_replaces_the_file_with_the_template(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"mine": true}', encoding="utf-8")

    init_repo(tmp_path, "dev", force=True)

    assert "mine" not in _settings(tmp_path)
    assert "Bash(kb *)" in _settings(tmp_path)["permissions"]["allow"]


def test_written_json_is_indent_2_with_trailing_newline(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = (tmp_path / ".claude" / "settings.json").read_bytes().decode("utf-8")
    assert text.endswith("}\n")
    assert '\n  "permissions": {' in text
    assert "\r" not in text


def test_recorded_lang_adds_its_test_command(tmp_path: Path):
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb" / "config.yaml").write_text(
        "repo_id: x\nkind: dev\nlangs: [python]\n", encoding="utf-8"
    )

    init_repo(tmp_path, "dev")

    allow = _settings(tmp_path)["permissions"]["allow"]
    assert "Bash(pytest *)" in allow
    assert "Bash(go test *)" not in allow


def test_lang_flag_adds_its_test_commands(tmp_path: Path):
    init_repo(tmp_path, "dev", langs=["ts", "java"])

    allow = _settings(tmp_path)["permissions"]["allow"]
    for entry in ("Bash(npm test*)", "Bash(npx *)", "Bash(mvn *)", "Bash(gradle *)"):
        assert entry in allow


def test_ba_gets_no_language_test_commands(tmp_path: Path):
    init_repo(tmp_path, "ba", langs=["python"])
    assert "Bash(pytest *)" not in _settings(tmp_path)["permissions"]["allow"]


def test_test_commands_cover_every_conventions_language():
    assert set(TEST_COMMANDS) == set(conventions.LANG_IDS)


def test_merge_settings_does_not_mutate_inputs():
    existing = {"permissions": {"allow": ["a"]}}
    template = json.loads(read_template("claude-settings-auto.json"))
    snapshot = json.dumps(existing)

    merged = merge_settings(existing, template)

    assert json.dumps(existing) == snapshot
    assert merged["permissions"]["allow"][0] == "a"
