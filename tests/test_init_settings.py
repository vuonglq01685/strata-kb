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

    assert "Bash(kb ticket *)" in settings["permissions"]["allow"]
    assert "mcp__strata-kb__*" in settings["permissions"]["allow"]
    assert "Bash(git push *main*)" in settings["permissions"]["deny"]
    assert "Edit(.claude/settings.json)" in settings["permissions"]["deny"]
    for event in ("Stop", "SubagentStop"):
        assert _commands(settings, event) == [USAGE_CMD]


@pytest.mark.parametrize("kind", ["ba", "dev"])
def test_template_never_grants_bypass(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    text = (tmp_path / ".claude" / "settings.json").read_text("utf-8")
    assert "bypassPermissions" not in text
    assert "dangerously" not in text


def test_hub_and_child_do_not_scaffold_settings_json():
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
    assert "Bash(kb ticket *)" in allow
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
    assert "Bash(kb ticket *)" in _settings(tmp_path)["permissions"]["allow"]


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
    for entry in ("Bash(npm test*)", "Bash(mvn test*)", "Bash(gradle test*)"):
        assert entry in allow
    for broad in ("Bash(npx *)", "Bash(mvn *)", "Bash(gradle *)", "Bash(composer *)"):
        assert broad not in allow


def test_lang_flag_ignored_when_config_already_records_langs(tmp_path: Path):
    (tmp_path / ".kb").mkdir()
    (tmp_path / ".kb" / "config.yaml").write_text(
        "repo_id: x\nkind: dev\nlangs: [python]\n", encoding="utf-8"
    )

    report = init_repo(tmp_path, "dev", langs=["go"])

    allow = _settings(tmp_path)["permissions"]["allow"]
    assert any("--lang ignored" in n for n in report.notes)
    assert "Bash(pytest *)" in allow
    assert "Bash(go test *)" not in allow


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


def test_non_list_hook_group_hooks_is_left_alone_with_a_note(tmp_path: Path):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    probe = '{"hooks":{"Stop":[{"hooks":null}]}}'
    path.write_text(probe, encoding="utf-8")

    report = init_repo(tmp_path, "dev")

    assert path.read_text("utf-8") == probe
    assert any("settings.json" in n for n in report.notes)


def test_merge_settings_raises_value_error_on_non_list_hook_group_hooks():
    template = json.loads(read_template("claude-settings-auto.json"))
    with pytest.raises(ValueError):
        merge_settings({"hooks": {"Stop": [{"hooks": None}]}}, template)


ALLOW = [
    "Bash(git add *)",
    "Bash(git commit *)",
    "Bash(git status*)",
    "Bash(git diff*)",
    "Bash(git log*)",
    "Bash(git fetch *)",
    "Bash(git pull)",
    "Bash(git pull origin *)",
    "Bash(git switch -c *)",
    "Bash(git switch auto/*)",
    "Bash(git switch fix/*)",
    "Bash(git switch hotfix/*)",
    "Bash(git checkout -b *)",
    "Bash(git branch *)",
    "Bash(git worktree *)",
    "Bash(git merge *)",
    "Bash(git push -u origin HEAD)",
    "Bash(git push origin HEAD)",
    "Bash(git push)",
    "Bash(gh pr *)",
    "Bash(gh run view*)",
    "Bash(gh run watch*)",
    "Bash(gh run rerun*)",
    "Bash(gh run list*)",
    "Edit",
    "Write",
    "Read",
    "mcp__strata-kb__*",
    "Bash(kb mission *)",
    "Bash(kb ticket *)",
    "Bash(kb publish*)",
    "Bash(kb svc *)",
    "Bash(kb impl *)",
    "Bash(kb plan *)",
    "Bash(kb pr *)",
    "Bash(kb resolve *)",
    "Bash(kb context *)",
    "Bash(kb query *)",
    "Bash(kb doctor*)",
    "Bash(kb code-ingest*)",
    "Bash(kb usage *)",
    "Bash(kb auto status*)",
]
DENY = [
    "Bash(git push *main*)",
    "Bash(git push *master*)",
    "Bash(git push *--force*)",
    "Bash(git push * -f*)",
    "Bash(git push *:*)",
    "Bash(git push *+*)",
    "Bash(git push *--delete*)",
    "Bash(git checkout main*)",
    "Bash(git checkout master*)",
    "Bash(git switch main*)",
    "Bash(git switch master*)",
    "Bash(git reset --hard*)",
    "Bash(gh repo delete *)",
    "Bash(gh run delete*)",
    "Bash(kb init*)",
    "Bash(kb auto on*)",
    "Bash(kb auto off*)",
    "Bash(kb auto run*)",
    "Bash(rm -rf /*)",
    "Edit(.claude/settings.json)",
    "Edit(.claude/settings.local.json)",
    "Write(.claude/settings.json)",
    "Write(.claude/settings.local.json)",
]


@pytest.mark.parametrize("kind", ["ba", "dev"])
def test_fresh_repo_permissions_are_exactly_the_reviewed_lists(
    tmp_path: Path, kind: str
):
    # Security surface: an unattended run must not push to main, force-push or
    # edit its own settings. Any change here is a deliberate, reviewed one.
    init_repo(tmp_path, kind)

    permissions = _settings(tmp_path)["permissions"]

    assert permissions["allow"] == ALLOW
    assert permissions["deny"] == DENY
