import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from center_kb import initcmd
from center_kb.cli import app
from center_kb.initcmd import expected_files, init_repo
from tests.cli_stub import write_cli_stub

# The CI dispatch step under test is a bash script, and the workflow that
# runs it is `runs-on: ubuntu-latest` — it never executes on Windows in
# production, so skipping there is the contract, not a coverage gap.
#
# The platform check is NOT redundant with the `which` check. On a GitHub
# Windows runner `shutil.which("bash")` resolves to
# C:\Windows\System32\bash.exe — the WSL launcher stub — which exits 1
# printing "Windows Subsystem for Linux has no installed distributions" in
# UTF-16, rather than running the script. A bash that exists but is not a
# shell defeats a presence-only guard, which is exactly how these four
# tests reached CI red on Windows while passing everywhere else.
_needs_bash = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="the dispatch step is a bash script; its workflow is ubuntu-only",
)

runner = CliRunner()


def test_init_hub_creates_all_hub_files(tmp_path: Path):
    report = init_repo(tmp_path, "hub")
    assert sorted(report.created) == sorted(expected_files("hub"))
    assert report.skipped == []
    for rel in expected_files("hub"):
        assert (tmp_path / rel).is_file(), rel
    # hub-only artifacts present
    assert (tmp_path / "federation" / "README.md").is_file()
    assert (tmp_path / ".env.example").is_file()


def test_init_rejects_unknown_kind(tmp_path: Path):
    with pytest.raises(ValueError):
        init_repo(tmp_path, "server")


def test_init_hub_config_has_kind_and_repo_id(tmp_path: Path):
    repo = tmp_path / "my-hub-repo"
    repo.mkdir()
    init_repo(repo, "hub")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: hub" in text
    assert 'hub: "."' in text
    assert 'repo_id: "my-hub-repo"' in text
    assert "{repo_id}" not in text


def test_init_refreshes_scaffold_but_protects_index(tmp_path: Path):
    init_repo(tmp_path, "hub")
    index = tmp_path / ".kb" / "index.yaml"
    index.write_text("docs: [{id: keep-me, title: X}]\n", encoding="utf-8")
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    skill.write_text("stale skill content\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub")
    assert report.created == []
    assert sorted(report.skipped) == sorted([".kb/index.yaml", ".kb/config.yaml"])
    assert ".claude/skills/kb-summarize/SKILL.md" in report.updated
    assert "keep-me" in index.read_text(encoding="utf-8")
    assert "stale skill content" not in skill.read_text(encoding="utf-8")


def test_init_is_idempotent_when_already_current(tmp_path: Path):
    init_repo(tmp_path, "hub")
    report = init_repo(tmp_path, "hub")
    assert report.created == []
    assert report.updated == []
    assert sorted(report.skipped) == sorted([".kb/index.yaml", ".kb/config.yaml"])


def test_init_force_overwrites_protected_data(tmp_path: Path):
    init_repo(tmp_path, "hub")
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: gone, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub", force=True)
    assert report.created == []
    assert ".kb/index.yaml" in report.updated
    assert report.skipped == []
    assert "gone" not in marker.read_text(encoding="utf-8")


def test_init_records_kind_in_legacy_config_without_touching_values(tmp_path):
    init_repo(tmp_path, "hub")
    cfg = tmp_path / ".kb" / "config.yaml"
    cfg.write_text("# my comment\nhub: /my/hub\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub")
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# my comment\nhub: /my/hub\n")
    assert "kind: hub" in text
    assert ".kb/config.yaml (kind recorded)" in report.updated
    assert ".kb/config.yaml" not in report.skipped


def test_init_does_not_duplicate_kind_line(tmp_path):
    init_repo(tmp_path, "hub")
    cfg = tmp_path / ".kb" / "config.yaml"
    report = init_repo(tmp_path, "hub")
    text = cfg.read_text(encoding="utf-8")
    # Count actual `kind:` assignment lines only; the template's own comment
    # ("# kind: this repo's role...") also contains the substring "kind:",
    # so a raw text.count("kind:") would always be 2 regardless of dupes.
    kind_lines = [line for line in text.splitlines() if line.startswith("kind:")]
    assert len(kind_lines) == 1
    assert ".kb/config.yaml" in report.skipped  # normal protected skip


def test_kb_doctor_on_fresh_skeleton_requires_hub(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["doctor", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 1
    assert "config.yaml" in result.output


def test_cli_init_hub_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb docker-setup" in result.output
    assert "docker compose up -d" in result.output
    # re-run: persisted kind, no flag needed, idempotent
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "0 created" in result2.output
    assert "0 updated" in result2.output
    assert "2 skipped" in result2.output


def test_cli_init_child_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "child"])
    assert result.exit_code == 0
    assert "Fill hub:" in result.output
    assert "kb publish" in result.output
    assert "docker compose up -d" not in result.output


def test_cli_init_updates_stale_scaffold(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    skill.write_text("stale\n", encoding="utf-8")
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 0
    assert "updated" in result.output
    assert "stale" not in skill.read_text(encoding="utf-8")


def test_cli_init_non_interactive_requires_kind(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 2
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_cli_init_conflicting_kind_errors(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path), "--kind", "child"])
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 1
    assert "already initialized as 'child'" in result.output
    # nothing was scaffolded as hub
    assert not (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt(tmp_path: Path, monkeypatch):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="hub\n")
    assert result.exit_code == 0
    assert "Central knowledge hub" in result.output      # description shown
    assert "Authoring repo" in result.output
    assert (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt_rejects_invalid_then_accepts(
    tmp_path: Path, monkeypatch
):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="server\nchild\n")
    assert result.exit_code == 0
    assert (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8").count(
        "kind: child"
    ) == 1


@pytest.mark.parametrize("kind", ["hub", "child"])
def test_quickstart_uses_correct_ingest_flag(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    text = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "--id" in text
    assert "--doc-id" not in text


def test_init_scaffolds_ai_integration_files(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    copilot = tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    assert skill.is_file() and copilot.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    assert "name: kb-summarize" in skill_text
    assert "VERBATIM" in skill_text            # writing rules present
    assert "kb build" in skill_text
    copilot_text = copilot.read_text(encoding="utf-8")
    assert 'applyTo: ".kb/**"' in copilot_text
    assert "25 words" in copilot_text


def test_init_scaffolds_kb_ingest_slash_command(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = tmp_path / ".claude" / "skills" / "kb-ingest" / "SKILL.md"
    prompt = tmp_path / ".github" / "prompts" / "kb-ingest.prompt.md"
    assert skill.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-ingest" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "source/" in text                     # default folder
        assert "sources/" not in text                # spec: singular only
        assert "NEVER run `kb ingest`" in text       # hard rule present
        assert "revision" in text and "tags" in text
        assert '"none" is a valid answer' in text
        assert "docker compose run --rm hub kb ingest" in text
        assert "--no-summarize" in text
        assert "docker info" in text


def test_init_scaffolds_kb_publish_slash_command(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md"
    prompt = tmp_path / ".github" / "prompts" / "kb-publish.prompt.md"
    assert skill.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-publish" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "NEVER run `kb publish`" in text          # hard rule
        assert "PR" in text                               # PR-mode publish
        assert "kb diff" in text
        assert "kb status" in text
        assert "CENTER_KB_HUB" in text
        assert "kb doctor" in text


@pytest.mark.parametrize("kind", ["hub", "child"])
def test_quickstart_and_instructions_have_cli_reference(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    quick = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (quick, instr):
        assert "## CLI reference" in text
        # every kb command appears
        for cmd in (
            "kb init", "kb ingest", "kb summarize", "kb status", "kb build",
            "kb query", "kb get", "kb stats", "kb diff",
            "kb publish", "kb resolve", "kb doctor",
        ):
            assert cmd in text, cmd
        assert "--level l2|l3" in text
        assert "l1|l2|l3" not in text
    assert "/kb-ingest" in quick
    assert "/kb-publish" in quick
    assert "/kb-summarize" in quick


def test_init_child_creates_child_files_only(tmp_path: Path):
    report = init_repo(tmp_path, "child")
    assert sorted(report.created) == sorted(expected_files("child"))
    # child never hosts federation or the long-lived server
    assert not (tmp_path / "federation").exists()
    assert not (tmp_path / ".env.example").exists()
    # authoring skills are still there
    assert (tmp_path / ".claude" / "skills" / "kb-ingest" / "SKILL.md").is_file()
    assert (tmp_path / ".github" / "workflows" / "kb-publish.yml").is_file()


def test_init_child_config_points_at_no_hub_yet(tmp_path: Path):
    repo = tmp_path / "my-child-repo"
    repo.mkdir()
    init_repo(repo, "child")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: child" in text
    assert 'hub: ""' in text
    assert 'repo_id: "my-child-repo"' in text


def test_child_kb_publish_workflow_uses_oidc_intake(tmp_path: Path):
    init_repo(tmp_path, "child")
    content = (
        tmp_path / ".github" / "workflows" / "kb-publish.yml"
    ).read_text(encoding="utf-8")
    assert 'tags: ["kb-publish/*"]' in content
    assert "id-token: write" in content
    assert "kb ci-publish" in content
    assert "secrets.GH_TOKEN" not in content
    assert "secrets.KB_HUB_URL" not in content
    assert "branches: [main]" not in content


def test_child_config_documents_intake(tmp_path: Path):
    init_repo(tmp_path, "child")
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "intake:" in text


def test_child_compose_is_ingest_only(tmp_path: Path):
    init_repo(tmp_path, "child")
    text = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert "hub:" in text          # service name stays `hub` (shared skill text)
    assert "ports:" not in text    # no long-lived HTTP server
    assert "env_file" not in text
    assert "healthcheck" not in text
    assert "docker compose run --rm hub kb ingest" in text


def test_child_mcp_json_uses_env_expansion(tmp_path: Path):
    init_repo(tmp_path, "child")
    text = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    assert '"type": "http"' in text
    assert "${CENTER_KB_HUB_URL}/mcp" in text
    assert "Bearer ${CENTER_KB_HTTP_TOKEN}" in text


def test_quickstarts_match_kind(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    hub_q = (hub_repo / "QUICKSTART.md").read_text(encoding="utf-8")
    child_q = (child_repo / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "kb docker-setup" in hub_q
    assert "docker compose up -d" in hub_q
    assert "kb docker-setup" in child_q
    assert "docker compose up -d" not in child_q
    assert "hub:" in child_q and "kb publish" in child_q
    for text in (hub_q, child_q):
        assert "## CLI reference" in text
        assert "/kb-ingest" in text and "/kb-publish" in text


def test_kb_summarize_templates_have_prose_only_rules(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (skill, instr):
        assert "Summarize the prose ONLY" in text
        assert "Table-only section:" in text


def test_init_scaffolds_kb_summarize_slash_command(tmp_path: Path):
    init_repo(tmp_path, "hub")
    command = tmp_path / ".claude" / "commands" / "kb-summarize.md"
    assert command.is_file()
    text = command.read_text(encoding="utf-8")
    assert "kb-summarize" in text          # invokes the skill by name
    assert "$ARGUMENTS" in text            # forwards the doc-id filter
    assert "argument-hint" in text


def test_init_scaffolds_kb_docker_setup_both_kinds(tmp_path: Path):
    for kind in ("hub", "child"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        skill = repo / ".claude" / "skills" / "kb-docker-setup" / "SKILL.md"
        command = repo / ".claude" / "commands" / "kb-docker-setup.md"
        prompt = repo / ".github" / "prompts" / "kb-docker-setup.prompt.md"
        assert skill.exists() and command.exists() and prompt.exists(), kind
        skill_text = skill.read_text(encoding="utf-8")
        assert "name: kb-docker-setup" in skill_text
        for text in (skill_text, prompt.read_text(encoding="utf-8")):
            assert "kb docker-setup" in text  # wraps the CLI
            assert "NEVER print" in text      # secret-hygiene rule
        assert "mode: agent" in prompt.read_text(encoding="utf-8")
        command_text = command.read_text(encoding="utf-8")
        assert "kb-docker-setup" in command_text  # invokes the skill by name


def test_init_scaffolds_kb_approve_both_kinds(tmp_path: Path):
    for kind in ("hub", "child"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        skill = repo / ".claude" / "skills" / "kb-approve" / "SKILL.md"
        command = repo / ".claude" / "commands" / "kb-approve.md"
        prompt = repo / ".github" / "prompts" / "kb-approve.prompt.md"
        cursor = repo / ".cursor" / "commands" / "kb-approve.md"
        assert skill.exists() and command.exists() and prompt.exists(), kind
        assert cursor.exists(), kind
        skill_text = skill.read_text(encoding="utf-8")
        assert "name: kb-approve" in skill_text
        assert "mode: agent" in prompt.read_text(encoding="utf-8")
        for text in (
            skill_text,
            prompt.read_text(encoding="utf-8"),
            cursor.read_text(encoding="utf-8"),
        ):
            assert "kb approve" in text            # wraps the CLI
            assert "_manifest.yaml" in text        # forbids hand-editing rule
        assert "kb-approve" in command.read_text(encoding="utf-8")


def test_init_scaffolds_cursor_commands_and_rule(tmp_path: Path):
    init_repo(tmp_path, "child")
    for name in ("kb-ingest", "kb-publish", "kb-summarize"):
        cmd = tmp_path / ".cursor" / "commands" / f"{name}.md"
        assert cmd.is_file(), name
        assert f"name: {name}" in cmd.read_text(encoding="utf-8")
    ingest = (tmp_path / ".cursor" / "commands" / "kb-ingest.md").read_text(
        encoding="utf-8"
    )
    assert "NEVER run `kb ingest`" in ingest
    assert "docker compose run --rm hub kb ingest" in ingest
    publish = (tmp_path / ".cursor" / "commands" / "kb-publish.md").read_text(
        encoding="utf-8"
    )
    assert "NEVER run `kb publish`" in publish
    rule = tmp_path / ".cursor" / "rules" / "kb-summarize.mdc"
    assert rule.is_file()
    rule_text = rule.read_text(encoding="utf-8")
    assert "globs: .kb/**" in rule_text
    assert "Summarize the prose ONLY" in rule_text
    assert "Table-only section:" in rule_text


def test_init_scaffolds_cursor_mcp_per_kind(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    hub_mcp = (hub_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "center_kb.mcp" in hub_mcp                      # stdio, same as .mcp.json
    assert hub_mcp == (hub_repo / ".mcp.json").read_text(encoding="utf-8")
    child_mcp = (child_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "${env:CENTER_KB_HUB_URL}/mcp" in child_mcp     # Cursor env syntax
    assert "Bearer ${env:CENTER_KB_HTTP_TOKEN}" in child_mcp


def test_assistant_slash_command_parity(tmp_path: Path):
    """Every kb-* command exists for Claude, Copilot, and Cursor in each kind."""
    common = ["kb-ingest", "kb-publish", "kb-summarize", "kb-init"]
    layouts = {
        "claude": lambda n: (
            Path(".claude/commands") / f"{n}.md"
            if n in ("kb-summarize", "kb-docker-setup", "kb-approve")
            else Path(".claude/skills") / n / "SKILL.md"
        ),
        "copilot": lambda n: (
            Path(".github/instructions/kb-summarize.instructions.md")
            if n == "kb-summarize"
            else Path(".github/prompts") / f"{n}.prompt.md"
        ),
        "cursor": lambda n: Path(".cursor/commands") / f"{n}.md",
    }
    common = common + ["kb-docker-setup", "kb-approve"]
    for kind, names in (("hub", common), ("child", common)):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        for assistant, layout in layouts.items():
            for name in names:
                assert (repo / layout(name)).is_file(), (kind, assistant, name)


def test_cursor_docker_setup_command_both_kinds(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    for repo in (hub_repo, child_repo):
        cmd = repo / ".cursor" / "commands" / "kb-docker-setup.md"
        assert cmd.is_file()
        text = cmd.read_text(encoding="utf-8")
        assert "NEVER print" in text


def test_kb_summarize_skill_is_parallel_orchestrator(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "READ-ONLY" in skill                      # sub-agents never write
    assert '"table_only"' in skill                   # JSON output contract
    assert '"l2_summary"' in skill
    assert '"l1_summary"' in skill
    assert "batches of ~5" in skill                  # granularity
    assert "at most 10" in skill                     # concurrency cap
    assert "kb build --allow-pending" in skill       # per-wave verify
    assert "single message" in skill                 # concurrent dispatch
    assert "one retry only" in skill                 # error handling
    assert "Do not edit many files in parallel" not in skill  # old rule gone


def test_record_asset_store_appends_s3_block(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("kind: hub\nhub: '.'\n", encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "s3") == "recorded"
    text = cfg.read_text(encoding="utf-8")
    assert "kind: hub" in text  # existing content preserved
    assert "asset_store:" in text and "mode: s3" in text
    assert 'bucket: ""' in text and 'prefix: "assets/"' in text
    # parses into the spec B model
    from center_kb import config as config_mod

    assert config_mod.load_config(tmp_path).asset_store.mode == "s3"


def test_record_asset_store_appends_none_block(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("kind: hub\n", encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "none") == "recorded"
    from center_kb import config as config_mod

    assert config_mod.load_config(tmp_path).asset_store.mode == "none"


def test_record_asset_store_never_rewrites_existing_block(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    original = "kind: hub\nasset_store:\n  mode: s3\n  bucket: my-bucket\n"
    cfg.write_text(original, encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "none") == "exists"
    assert cfg.read_text(encoding="utf-8") == original


def test_record_asset_store_missing_config(tmp_path: Path):
    assert initcmd.record_asset_store(tmp_path / "config.yaml", "s3") == "no-config"


def test_init_repo_assets_records_block_and_reports(tmp_path: Path):
    initcmd.init_repo(tmp_path, "hub")
    report = initcmd.init_repo(tmp_path, "hub", assets="s3")
    assert any("asset_store recorded" in u for u in report.updated)
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "mode: s3" in text


def test_init_repo_assets_exists_notes_left_unchanged(tmp_path: Path):
    initcmd.init_repo(tmp_path, "hub", assets="s3")
    report = initcmd.init_repo(tmp_path, "hub", assets="none")
    assert any("left unchanged" in n for n in report.notes)
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "mode: s3" in text and "mode: none" not in text


def test_cli_init_assets_rejected_for_child(tmp_path: Path):
    result = runner.invoke(
        app, ["init", str(tmp_path), "--kind", "child", "--assets", "s3"]
    )
    assert result.exit_code == 2
    assert "hub" in result.output


def test_init_scaffolds_kb_init_command_templates(tmp_path):
    initcmd.init_repo(tmp_path, "hub")
    for rel in (
        ".claude/skills/kb-init/SKILL.md",
        ".claude/commands/kb-init.md",
        ".github/prompts/kb-init.prompt.md",
        ".cursor/commands/kb-init.md",
    ):
        assert (tmp_path / rel).is_file(), rel


# --- Phase 4: kind `ba` (BA requirements repo) ------------------------------

_BA_SPEC_8_PATHS = (
    ".kb/config.yaml",
    ".mcp.json",
    ".cursor/mcp.json",
    ".claude/skills/ba-ticket-author/SKILL.md",
    ".claude/commands/ba-ticket-author.md",
    ".github/prompts/ba-ticket-author.prompt.md",
    ".cursor/commands/ba-ticket-author.md",
    "docs/tickets/TEMPLATE.md",
    "tickets/.gitkeep",
    ".github/workflows/kb-ticket-lint.yml",
    "QUICKSTART-BA.md",
)

# The exact hub/child expected-file sets as they existed before this plan —
# used to assert Phase 4 added nothing to hub/child (byte-for-byte).
_PRE_PHASE4_HUB_FILES = [
    ".claude/commands/kb-approve.md",
    ".claude/commands/kb-docker-setup.md",
    ".claude/commands/kb-init.md",
    ".claude/commands/kb-summarize.md",
    ".claude/skills/kb-approve/SKILL.md",
    ".claude/skills/kb-docker-setup/SKILL.md",
    ".claude/skills/kb-ingest/SKILL.md",
    ".claude/skills/kb-init/SKILL.md",
    ".claude/skills/kb-publish/SKILL.md",
    ".claude/skills/kb-summarize/SKILL.md",
    ".cursor/commands/kb-approve.md",
    ".cursor/commands/kb-docker-setup.md",
    ".cursor/commands/kb-ingest.md",
    ".cursor/commands/kb-init.md",
    ".cursor/commands/kb-publish.md",
    ".cursor/commands/kb-summarize.md",
    ".cursor/mcp.json",
    ".cursor/rules/kb-summarize.mdc",
    ".env.example",
    ".github/instructions/kb-summarize.instructions.md",
    ".github/prompts/kb-approve.prompt.md",
    ".github/prompts/kb-docker-setup.prompt.md",
    ".github/prompts/kb-ingest.prompt.md",
    ".github/prompts/kb-init.prompt.md",
    ".github/prompts/kb-publish.prompt.md",
    ".github/workflows/kb-publish.yml",
    ".kb/config.yaml",
    ".kb/index.yaml",
    ".mcp.json",
    "QUICKSTART.md",
    "docker-compose.yml",
    "federation/README.md",
    "source/.gitignore",
]

_PRE_PHASE4_CHILD_FILES = [
    ".claude/commands/kb-approve.md",
    ".claude/commands/kb-docker-setup.md",
    ".claude/commands/kb-init.md",
    ".claude/commands/kb-summarize.md",
    ".claude/skills/kb-approve/SKILL.md",
    ".claude/skills/kb-docker-setup/SKILL.md",
    ".claude/skills/kb-ingest/SKILL.md",
    ".claude/skills/kb-init/SKILL.md",
    ".claude/skills/kb-publish/SKILL.md",
    ".claude/skills/kb-summarize/SKILL.md",
    ".cursor/commands/kb-approve.md",
    ".cursor/commands/kb-docker-setup.md",
    ".cursor/commands/kb-ingest.md",
    ".cursor/commands/kb-init.md",
    ".cursor/commands/kb-publish.md",
    ".cursor/commands/kb-summarize.md",
    ".cursor/mcp.json",
    ".cursor/rules/kb-summarize.mdc",
    ".github/instructions/kb-summarize.instructions.md",
    ".github/prompts/kb-approve.prompt.md",
    ".github/prompts/kb-docker-setup.prompt.md",
    ".github/prompts/kb-ingest.prompt.md",
    ".github/prompts/kb-init.prompt.md",
    ".github/prompts/kb-publish.prompt.md",
    ".github/workflows/kb-publish.yml",
    ".kb/config.yaml",
    ".kb/index.yaml",
    ".mcp.json",
    "QUICKSTART.md",
    "docker-compose.yml",
    "source/.gitignore",
]


def test_init_kind_ba_scaffolds_minimal_set(tmp_path: Path):
    report = init_repo(tmp_path, "ba")
    assert sorted(report.created) == sorted(expected_files("ba"))
    for rel in _BA_SPEC_8_PATHS:
        assert (tmp_path / rel).is_file(), rel
    # authoring wrappers are explicitly NOT on kind `ba`
    for name in ("kb-ingest", "kb-summarize", "kb-approve", "kb-publish", "kb-docker-setup"):
        assert not (tmp_path / ".claude" / "skills" / name).exists(), name
        assert not (tmp_path / ".claude" / "commands" / f"{name}.md").exists(), name
        assert not (tmp_path / ".github" / "prompts" / f"{name}.prompt.md").exists(), name
        assert not (tmp_path / ".cursor" / "commands" / f"{name}.md").exists(), name
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()
    assert not (tmp_path / "source").exists()
    assert not (tmp_path / "federation").exists()
    assert not (tmp_path / ".env.example").exists()
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: ba" in text


def test_init_rejects_unknown_kind_still_excludes_ba_typos(tmp_path: Path):
    with pytest.raises(ValueError):
        init_repo(tmp_path, "BA")


def test_hub_child_unchanged_by_phase4(tmp_path: Path):
    assert sorted(expected_files("hub")) == sorted(_PRE_PHASE4_HUB_FILES)
    assert sorted(expected_files("child")) == sorted(_PRE_PHASE4_CHILD_FILES)
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    for repo in (hub_repo, child_repo):
        assert not (repo / ".claude" / "skills" / "ba-ticket-author").exists()
        assert not (repo / ".claude" / "commands" / "ba-ticket-author.md").exists()
        assert not (repo / ".github" / "prompts" / "ba-ticket-author.prompt.md").exists()
        assert not (repo / ".cursor" / "commands" / "ba-ticket-author.md").exists()
        assert not (repo / "docs" / "tickets" / "TEMPLATE.md").exists()
        assert not (repo / ".github" / "workflows" / "kb-ticket-lint.yml").exists()


def test_init_ba_config_has_kind_and_repo_id(tmp_path: Path):
    repo = tmp_path / "my-ba-repo"
    repo.mkdir()
    init_repo(repo, "ba")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: ba" in text
    assert 'hub: ""' in text
    assert 'repo_id: "my-ba-repo"' in text
    assert "{repo_id}" not in text


def test_ba_mcp_json_reuses_child_template(tmp_path: Path):
    ba_repo = tmp_path / "b"
    child_repo = tmp_path / "c"
    ba_repo.mkdir()
    child_repo.mkdir()
    init_repo(ba_repo, "ba")
    init_repo(child_repo, "child")
    assert (ba_repo / ".mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".mcp.json"
    ).read_text(encoding="utf-8")
    assert (ba_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".cursor" / "mcp.json"
    ).read_text(encoding="utf-8")


def test_kb_ticket_lint_workflow_content(tmp_path: Path):
    init_repo(tmp_path, "ba")
    content = (
        tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml"
    ).read_text(encoding="utf-8")
    assert "pull_request" in content
    # Deliberately NOT `paths`-filtered: GitHub never synthesizes a passing
    # status for a job that never started, so filtering the trigger of a
    # *required* check would leave a PR touching neither tickets/ nor
    # missions/ waiting forever. The job must always start; the one lint
    # step below decides for itself whether there was anything to check.
    # (Checks the literal old trigger filter, not the substring 'paths:' —
    # that substring also appears in this file's own explanatory comments.)
    assert 'paths: ["tickets/**.md", "missions/**.md"]' not in content
    assert "pip install center-kb" in content
    assert "kb ticket lint" in content
    assert "vars.CENTER_KB_HUB" in content
    assert "secrets.KB_HUB_TOKEN" in content
    # no hardcoded credential/URL — only GH Actions expressions
    assert "kb.internal" not in content
    assert "example.com" not in content
    assert "ghp_" not in content  # no literal token-shaped string


def test_quickstart_ba_content(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = (tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8")
    assert "pip install center-kb" in text
    assert "CENTER_KB_HUB_URL" in text
    assert "CENTER_KB_HTTP_TOKEN" in text
    assert "/ba-ticket-author" in text
    assert "tickets/" in text
    assert "DoR" in text
    assert "Definition of Ready" in text
    assert "branch" in text.lower()  # branch-protection note


def test_cli_init_ba_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "ba"])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "ba-ticket-author" in result.output
    assert "QUICKSTART-BA.md" in result.output
    assert "kb docker-setup" not in result.output
    assert "kb ingest" not in result.output


def test_cli_init_assets_rejected_for_ba(tmp_path: Path):
    result = runner.invoke(
        app, ["init", str(tmp_path), "--kind", "ba", "--assets", "s3"]
    )
    assert result.exit_code == 2
    assert "hub" in result.output


def test_resolve_kind_interactive_accepts_ba(tmp_path: Path, monkeypatch):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="ba\n")
    assert result.exit_code == 0
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert text.count("kind: ba") == 1
    assert (tmp_path / "QUICKSTART-BA.md").exists()


def test_resolve_kind_interactive_rejects_invalid_then_accepts_ba(
    tmp_path: Path, monkeypatch
):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="server\nba\n")
    assert result.exit_code == 0
    assert (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8").count(
        "kind: ba"
    ) == 1


def test_config_load_accepts_kind_ba(tmp_path: Path):
    from center_kb.config import load_config

    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    (kb_dir / "config.yaml").write_text("kind: ba\nhub: ''\n", encoding="utf-8")
    cfg = load_config(kb_dir)
    assert cfg.kind == "ba"


def test_ba_kind_scaffolds_the_mission_plan_set(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    mission_template = tmp_path / "docs" / "missions" / "TEMPLATE.md"
    assert mission_template.is_file()
    assert (tmp_path / "missions" / ".gitkeep").is_file()
    assert (tmp_path / "tickets" / ".gitkeep").is_file()
    # the scaffolded file must be the mission template, not merely present —
    # a mistyped BA_TEMPLATES source (e.g. pointing at ticket-template.md)
    # would still satisfy an existence-only assertion.
    assert "## US backlog" in mission_template.read_text(encoding="utf-8")


def test_hub_and_child_do_not_gain_mission_artifacts(tmp_path):
    from center_kb.initcmd import init_repo

    for kind in ("hub", "child"):
        target = tmp_path / kind
        target.mkdir()
        init_repo(target, kind)
        assert not (target / "missions").exists()
        assert not (target / "docs" / "missions").exists()
        for rel in (
            ".claude/skills/ba-mission-plan/SKILL.md",
            ".claude/commands/ba-mission-plan.md",
            ".github/prompts/ba-mission-plan.prompt.md",
            ".cursor/commands/ba-mission-plan.md",
        ):
            assert not (target / rel).exists(), rel


def test_ba_kind_scaffolds_the_mission_plan_skill(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    for rel in (
        ".claude/skills/ba-mission-plan/SKILL.md",
        ".claude/commands/ba-mission-plan.md",
        ".github/prompts/ba-mission-plan.prompt.md",
        ".cursor/commands/ba-mission-plan.md",
    ):
        assert (tmp_path / rel).is_file(), rel


def test_every_mission_wrapper_carries_the_no_silent_skip_rule(tmp_path):
    """kb mission lint has no MCP fallback, so 'kb unavailable is not a
    PASS' must appear in all four wrappers — it is the only thing standing
    between a missing binary and a silently unlinted mission."""
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    for rel in (
        ".claude/skills/ba-mission-plan/SKILL.md",
        ".claude/commands/ba-mission-plan.md",
        ".github/prompts/ba-mission-plan.prompt.md",
        ".cursor/commands/ba-mission-plan.md",
    ):
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert "is not a PASS" in text, rel


def test_mission_wrappers_reference_the_required_headings(tmp_path):
    """Checked across all four wrappers, not just the Claude Code skill:
    the Copilot and Cursor wrappers each carry a SECOND copy of the
    required-heading list in their preamble, above '## Workflow' — outside
    the byte-identity slice that `test_mission_wrapper_workflow_bodies_are
    _byte_identical` enforces. Hard-coding the skill path here would leave
    that second copy able to drift from `REQUIRED_MISSION_HEADINGS`
    undetected."""
    from center_kb import mission
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")
    for rel in _MISSION_WRAPPER_PATHS:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        for heading in mission.REQUIRED_MISSION_HEADINGS:
            name = heading.removeprefix("## ")
            assert name in text, f"{rel}: missing {name!r}"


_MISSION_WRAPPER_PATHS = (
    ".claude/skills/ba-mission-plan/SKILL.md",
    ".claude/commands/ba-mission-plan.md",
    ".github/prompts/ba-mission-plan.prompt.md",
    ".cursor/commands/ba-mission-plan.md",
)

_TICKET_WRAPPER_PATHS = (
    ".claude/skills/ba-ticket-author/SKILL.md",
    ".claude/commands/ba-ticket-author.md",
    ".github/prompts/ba-ticket-author.prompt.md",
    ".cursor/commands/ba-ticket-author.md",
)


def test_mission_wrapper_workflow_bodies_are_byte_identical(tmp_path):
    """The four ba-mission-plan wrappers are supposed to be byte-identical
    from '## Workflow' to end of file — that property is the whole point
    of shipping four near-duplicate documents. A substring/heading check
    can pass while the bodies silently fork per host; only an exact slice
    comparison catches that drift."""
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    slices = []
    for rel in _MISSION_WRAPPER_PATHS:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        idx = text.index("## Workflow")
        slices.append(text[idx:])

    first = slices[0]
    for rel, body in zip(_MISSION_WRAPPER_PATHS, slices):
        assert body == first, f"{rel} Workflow body drifted from the others"


def test_ticket_wrappers_document_the_refs_inheritance_rule(tmp_path):
    """Regression guard for the parent-mission refs-inheritance rule. Three
    parts of the rule can each go missing independently from exactly one
    wrapper and stay undetected unless all three are asserted here: the
    'starting candidates only' phrase (dropping it would draft with the
    mission's full kb-context copied wholesale instead of pinning fresh
    refs), the `> Parent mission:` back-link line (dropping it breaks the
    ticket-lint back-link check), and the `tickets/<mission-id>-US<n>.md`
    filename convention (dropping it means the back-link check can't find
    the ticket at all)."""
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    for rel in _TICKET_WRAPPER_PATHS:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        assert "starting candidates" in text.lower(), rel
        assert "> Parent mission: <mission-id>" in text, rel
        assert "tickets/<mission-id>-US<n>.md" in text, rel


def test_mission_wrappers_carry_the_never_auto_rules(tmp_path):
    """Both 'never auto-generate' (ticket files from the backlog) and
    'never auto-pick' (ambiguous kb_search candidates) are load-bearing
    hard rules with no lint-time enforcement — a wrapper that drops either
    one relies entirely on the agent's own restraint."""
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    for rel in _MISSION_WRAPPER_PATHS:
        text = (tmp_path / rel).read_text(encoding="utf-8").lower()
        assert "never auto-generate" in text, rel
        assert "never auto-pick" in text, rel


def test_ci_gate_covers_both_tickets_and_missions(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")
    wf = (
        tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml"
    ).read_text(encoding="utf-8")

    # The trigger itself is not paths-filtered (see
    # test_kb_ticket_lint_workflow_content) — coverage of both directories
    # lives in the dispatch step's own `git diff` pathspec instead.
    assert "tickets/*.md" in wf
    assert "missions/*.md" in wf
    assert "kb ticket lint" in wf
    assert "kb mission lint" in wf


def test_ci_gate_job_name_is_frozen(tmp_path):
    """Branch protection on provisioned BA repos keys on the job name.
    Renaming it leaves those repos waiting forever on a required check
    that never runs again."""
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")
    wf_path = tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml"
    assert wf_path.is_file()
    wf = wf_path.read_text(encoding="utf-8")
    assert "name: kb-ticket-lint" in wf
    assert "\n  lint:\n" in wf


def test_ci_gate_has_no_hardcoded_credentials(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")
    wf = (
        tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml"
    ).read_text(encoding="utf-8")
    assert "secrets.KB_HUB_TOKEN" in wf
    assert "ghp_" not in wf


# --- CI gate: execute the real dispatch loop, not a substring check --------
#
# The three tests above are pure substring checks against the rendered YAML
# text. They pass unchanged if the `case` arms are swapped, if `status` never
# aggregates a failure, or if a non-ASCII/deleted path is silently skipped —
# exactly the two bugs that reached review. This section extracts the actual
# final step's `run:` script from the rendered workflow and executes it with
# bash against a hermetic git repo, so the dispatch logic itself is exercised.


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _extract_lint_dispatch_script(tmp_path: Path) -> str:
    """Scaffold a `ba` repo and pull the lint job's `Lint changed ...` step
    `run:` body out of the *rendered* workflow YAML — the exact script CI
    executes. Selected by step *name* rather than `steps[-1]` so this keeps
    finding the right script even if another step is appended later."""
    repo = tmp_path / "ba-scaffold"
    init_repo(repo, "ba")
    wf_text = (
        repo / ".github" / "workflows" / "kb-ticket-lint.yml"
    ).read_text(encoding="utf-8")
    data = yaml.safe_load(wf_text)
    steps = data["jobs"]["lint"]["steps"]
    for step in steps:
        if "Lint changed" in step.get("name", ""):
            return step["run"]
    raise AssertionError("no step with 'Lint changed' in its name in kb-ticket-lint.yml")


# The literal git-diff-into-tempfile block from the workflow's dispatch
# script. Used by `_replace_git_diff_with_synthetic_paths` below to swap in a
# synthetic path list for the loud-fallback-arm test, since that arm can
# never be reached through a *real* `git diff` — its own pathspec already
# confines every emitted path to tickets/ or missions/.
_GIT_DIFF_BLOCK = (
    "git -c core.quotePath=false diff -z --name-only --diff-filter=ACMR \\\n"
    '  "origin/${BASE_REF}..." \\\n'
    "  -- 'tickets/*.md' 'tickets/**/*.md' 'missions/*.md' 'missions/**/*.md' \\\n"
    '  > "$RUNNER_TEMP/changed.nul"\n'
)


def _replace_git_diff_with_synthetic_paths(run_script: str, paths: list[str]) -> str:
    assert _GIT_DIFF_BLOCK in run_script, (
        "the workflow's git-diff block text changed — update _GIT_DIFF_BLOCK "
        "to match kb-ticket-lint.yml"
    )
    printf_args = " ".join(f"'{p}'" for p in paths)
    replacement = f'printf \'%s\\0\' {printf_args} > "$RUNNER_TEMP/changed.nul"\n'
    return run_script.replace(_GIT_DIFF_BLOCK, replacement)


_KB_STUB_BODY = (
    "import os, sys\n"
    "log = os.environ.get('KB_STUB_LOG')\n"
    "if log:\n"
    "    with open(log, 'a', encoding='utf-8') as fh:\n"
    "        fh.write('\\t'.join(sys.argv[1:]) + '\\n')\n"
    "fail_markers = [m for m in os.environ.get('KB_STUB_FAIL', '').split(os.pathsep) if m]\n"
    "sys.exit(1 if any(a in fail_markers for a in sys.argv[1:]) else 0)\n"
)


@_needs_bash
def test_ci_gate_dispatch_loop_actually_dispatches(tmp_path):
    """Run the CI workflow's real final step under `bash -e` (the same
    invocation GitHub Actions uses for a `run:` block), not a substring
    match. Sets up a git repo that mimics a checked-out PR: a base commit
    with a ticket (`tickets/keep.md`), then a single PR commit that retires
    that ticket (deletes it — the file exists in the base commit, so it is a
    genuine two-endpoint deletion, not an add+delete pair invisible to
    `origin/main...HEAD`), adds a new ticket, and adds a mission whose
    filename is non-ASCII (Vietnamese). A stub `kb` on PATH records every
    invocation's argv and can be told to fail for a specific path via
    KB_STUB_FAIL.

    Verifies:
    - a `missions/*` path dispatches to `kb mission lint`, a `tickets/*`
      path dispatches to `kb ticket lint` (the pairing, not just presence);
    - the non-ASCII mission filename IS linted (Important 1 — it must not
      be silently skipped by the `*) continue ;;` fallback);
    - the deleted ticket (present in the base commit, absent from the PR
      commit) is never invoked at all, and does not fail the job
      (Important 2 — this only exercises anything because the deleted path
      actually exists at one diff endpoint, unlike a same-PR add+delete);
    - configuring the surviving ticket to fail makes the whole step exit
      non-zero (status aggregation actually works).
    """
    run_script = _extract_lint_dispatch_script(tmp_path)
    script_path = tmp_path / "lint-step.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")

    (repo / "tickets").mkdir()
    (repo / "tickets" / "keep.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tickets/keep.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    # PR commit: retire the ticket that existed in the base commit (delete),
    # add a new ticket, add a non-ASCII mission filename — the exact repro
    # from Important 1's bug report.
    _git(repo, "rm", "-q", "tickets/keep.md")
    (repo / "missions").mkdir(exist_ok=True)
    (repo / "missions" / "M-Đăng-nhập.md").write_text("mission\n", encoding="utf-8")
    (repo / "tickets").mkdir(exist_ok=True)
    (repo / "tickets" / "T-new.md").write_text("new ticket\n", encoding="utf-8")
    _git(repo, "add", "missions/M-Đăng-nhập.md", "tickets/T-new.md")
    _git(repo, "commit", "-q", "-m", "pr: retire+add ticket, add mission")

    bindir = tmp_path / "bin"
    write_cli_stub(bindir, "kb", _KB_STUB_BODY)
    log_path = tmp_path / "kb.log"

    base_env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "BASE_REF": "main",
        "CENTER_KB_HUB": "https://example.invalid/hub",
        "KB_STUB_LOG": str(log_path),
        "RUNNER_TEMP": str(tmp_path),
    }

    # --- Run 1: nothing configured to fail. ---
    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={**base_env, "KB_STUB_FAIL": ""},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log_lines = log_path.read_text(encoding="utf-8").splitlines()

    # Dispatch pairing: missions/ -> mission lint, tickets/ -> ticket lint.
    assert (
        "mission\tlint\tmissions/M-Đăng-nhập.md\t--hub\thttps://example.invalid/hub"
        in log_lines
    )
    assert (
        "ticket\tlint\ttickets/T-new.md\t--hub\thttps://example.invalid/hub"
        in log_lines
    )
    # The deleted ticket was never handed to `kb` at all.
    assert not any("keep.md" in line for line in log_lines)

    # --- Run 2: the surviving ticket is configured to fail lint. ---
    log_path.unlink()
    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={**base_env, "KB_STUB_FAIL": "tickets/T-new.md"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    # Both files were still attempted (one failure does not short-circuit
    # the loop) even though the job as a whole must fail.
    assert any("missions/M-Đăng-nhập.md" in line for line in log_lines)
    assert any("tickets/T-new.md" in line for line in log_lines)


@_needs_bash
def test_ci_gate_step_aborts_on_failing_git_diff(tmp_path):
    """Important A regression test.

    `done < <(git ... -z ...)` (process substitution) makes the substitution's
    exit status unobservable: if `git diff` fails outright (stale/empty
    BASE_REF, `origin/<base>` absent, any git error), it writes to stderr,
    produces zero records, the loop never runs, `count` stays 0, and the step
    printed the "no ticket or mission files changed" notice and exited 0 — a
    green check on a diff that was never computed. The fix runs `git diff` as
    a plain foreground command redirected into a temp file, so a failure
    trips `bash -e` (the same invocation GitHub Actions uses) immediately.

    Reproduces the failure by pointing BASE_REF at a branch that has no
    corresponding `refs/remotes/origin/<BASE_REF>` — the same shape as a
    stale or empty BASE_REF in real CI.
    """
    run_script = _extract_lint_dispatch_script(tmp_path)
    script_path = tmp_path / "lint-step.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo-bad-base-ref"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    (repo / "tickets").mkdir()
    (repo / "tickets" / "keep.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tickets/keep.md")
    _git(repo, "commit", "-q", "-m", "base")
    # Deliberately no `refs/remotes/origin/<BASE_REF>` — the failure mode.

    # A stub `kb` on PATH, logging every invocation. Any non-zero exit here
    # is consistent with `kb` itself failing lint on a real file — asserting
    # only `returncode != 0` (as this test used to) would pass just as
    # happily on that unrelated failure mode, so the abort cause must be
    # pinned to the `git diff` itself, and `kb` must be proven unreached.
    bindir = tmp_path / "bin"
    write_cli_stub(bindir, "kb", _KB_STUB_BODY)
    log_path = tmp_path / "kb.log"

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BASE_REF": "no-such-branch",
            "CENTER_KB_HUB": "https://example.invalid/hub",
            "KB_STUB_LOG": str(log_path),
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )
    # Pin the abort cause to the failing `git diff` itself (git's own exit
    # code for a fatal error, e.g. an unresolvable revision, is 128) rather
    # than accepting any non-zero exit — which would equally accept `kb`
    # itself failing lint on some file, a completely different bug.
    assert result.returncode != 0 and "fatal" in result.stderr, (
        "a failing `git diff` (bad BASE_REF) must abort the step instead of "
        f"falling through to the empty-diff notice and exiting 0: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    # It must NOT print the "nothing changed" notice — that would assert a
    # DoR lint pass/skip that never actually happened.
    assert "no ticket or mission files changed" not in result.stdout
    # `kb` must never have been invoked: the abort happens before the
    # dispatch loop, on the `git diff` populating the changed-files list.
    assert not log_path.exists(), log_path.read_text(encoding="utf-8")


@_needs_bash
def test_ci_gate_prints_notice_and_exits_zero_when_nothing_changed(tmp_path):
    """Minor 7 (first uncovered branch): the empty-diff path — a PR that
    touches no tickets/missions files at all — had no test. Assert it prints
    the skip notice and exits 0."""
    run_script = _extract_lint_dispatch_script(tmp_path)
    script_path = tmp_path / "lint-step.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo-empty-diff"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    (repo / "README.md").write_text("base\nchanged\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "pr: unrelated change")

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "BASE_REF": "main",
            "CENTER_KB_HUB": "https://example.invalid/hub",
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "::notice::no ticket or mission files changed — DoR lint skipped"
        in result.stdout
    )


@_needs_bash
def test_ci_gate_loud_fallback_arm_fails_without_short_circuiting(tmp_path):
    """Minor 6/7 (second uncovered branch): the `*) ... status=1 ;
    continue ;;` fallback arm can never be reached through a *real* `git
    diff` — its own pathspec ('tickets/*.md' etc.) already confines every
    emitted path to tickets/ or missions/, as the workflow's own comment now
    explains. Exercise the arm directly by swapping the git-diff-population
    line for a literal synthetic NUL-separated path list (leaving the loop,
    case dispatch, and status/count aggregation untouched), so a future
    pathspec widening that lets an unrelated path through would still be
    caught by this test.
    """
    run_script = _extract_lint_dispatch_script(tmp_path)
    run_script = _replace_git_diff_with_synthetic_paths(
        run_script, ["tickets/T-new.md", "docs/other.md", "missions/M-new.md"]
    )
    script_path = tmp_path / "lint-step-synthetic.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo-synthetic"
    (repo / "tickets").mkdir(parents=True)
    (repo / "missions").mkdir()
    (repo / "tickets" / "T-new.md").write_text("new\n", encoding="utf-8")
    (repo / "missions" / "M-new.md").write_text("mission\n", encoding="utf-8")

    bindir = tmp_path / "bin-synthetic"
    write_cli_stub(bindir, "kb", _KB_STUB_BODY)
    log_path = tmp_path / "kb-synthetic.log"

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BASE_REF": "main",
            "CENTER_KB_HUB": "https://example.invalid/hub",
            "KB_STUB_LOG": str(log_path),
            "KB_STUB_FAIL": "",
            "RUNNER_TEMP": str(tmp_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unrecognised path 'docs/other.md'" in result.stdout
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert not any("docs/other.md" in line for line in log_lines)
    # The loop did not short-circuit: both matched paths on either side of
    # the unrecognised one were still dispatched.
    assert any("tickets/T-new.md" in line for line in log_lines)
    assert any("missions/M-new.md" in line for line in log_lines)


# --- Phase 5 Stage A: kind `dev` (product code repo) ------------------------

_DEV_STAGE_A_PATHS = (
    ".kb/config.yaml",
    ".kb/index.yaml",
    ".mcp.json",
    ".cursor/mcp.json",
    "docs/impl/.gitkeep",
    "QUICKSTART-DEV.md",
    ".claude/skills/dev-implement-ticket/SKILL.md",
    ".claude/commands/dev-implement-ticket.md",
    ".github/prompts/dev-implement-ticket.prompt.md",
    ".cursor/commands/dev-implement-ticket.md",
    ".claude/skills/dev-design/SKILL.md",
    ".claude/skills/dev-plan/SKILL.md",
    ".claude/skills/dev-execute/SKILL.md",
    ".claude/skills/dev-handover/SKILL.md",
)


def test_init_kind_dev_scaffolds_exactly_the_stage_a_set(tmp_path: Path):
    report = init_repo(tmp_path, "dev")
    assert sorted(report.created) == sorted(expected_files("dev"))
    assert report.skipped == []
    for rel in _DEV_STAGE_A_PATHS:
        assert (tmp_path / rel).is_file(), rel


def test_init_kind_dev_has_all_four_wrappers_per_workflow_skill(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for skill in ("dev-implement-ticket", "dev-design", "dev-plan",
                  "dev-execute", "dev-handover"):
        assert (tmp_path / ".claude" / "skills" / skill / "SKILL.md").is_file(), skill
        assert (tmp_path / ".claude" / "commands" / f"{skill}.md").is_file(), skill
        assert (tmp_path / ".github" / "prompts" / f"{skill}.prompt.md").is_file(), skill
        assert (tmp_path / ".cursor" / "commands" / f"{skill}.md").is_file(), skill


def test_init_kind_dev_excludes_authoring_and_ba_artifacts(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for name in ("kb-ingest", "kb-docker-setup", "kb-init"):
        assert not (tmp_path / ".claude" / "skills" / name).exists(), name
        assert not (tmp_path / ".cursor" / "commands" / f"{name}.md").exists(), name
    for name in ("ba-ticket-author", "ba-mission-plan"):
        assert not (tmp_path / ".claude" / "skills" / name).exists(), name
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()
    assert not (tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml").exists()
    assert not (tmp_path / "source").exists()
    assert not (tmp_path / "federation").exists()
    assert not (tmp_path / "tickets").exists()
    assert not (tmp_path / "docs" / "tickets").exists()


def test_init_dev_config_has_kind_repo_id_and_intake(tmp_path: Path):
    repo = tmp_path / "my-dev-repo"
    repo.mkdir()
    init_repo(repo, "dev")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: dev" in text
    assert 'repo_id: "my-dev-repo"' in text
    assert "intake:" in text
    assert "hub:" in text
    assert text.count("kind: dev") == 1


def test_dev_mcp_json_reuses_the_child_templates(tmp_path: Path):
    dev_repo = tmp_path / "d"
    child_repo = tmp_path / "c"
    dev_repo.mkdir()
    child_repo.mkdir()
    init_repo(dev_repo, "dev")
    init_repo(child_repo, "child")
    assert (dev_repo / ".mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".mcp.json"
    ).read_text(encoding="utf-8")
    assert (dev_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8") == (
        child_repo / ".cursor" / "mcp.json"
    ).read_text(encoding="utf-8")


def test_phase5_adds_nothing_to_hub_child_or_ba(tmp_path: Path):
    assert sorted(expected_files("hub")) == _PRE_PHASE4_HUB_FILES
    assert sorted(expected_files("child")) == _PRE_PHASE4_CHILD_FILES
    for rel in expected_files("ba"):
        assert "dev-" not in rel, rel


def test_config_accepts_kind_dev(tmp_path: Path):
    from center_kb.config import load_config

    init_repo(tmp_path, "dev")
    assert load_config(tmp_path / ".kb").kind == "dev"


def test_init_cli_accepts_kind_dev(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "dev"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "skills" / "dev-design" / "SKILL.md").is_file()


def test_cli_init_dev_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "dev"])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "dev-implement-ticket" in result.output
    assert "QUICKSTART-DEV.md" in result.output
    assert "federation/registry.yaml" in result.output
    assert "ba-ticket-author" not in result.output
    assert "kb ingest" not in result.output
    assert "(details: QUICKSTART-DEV.md)" in result.output


def test_kind_descriptions_lists_four_kinds():
    from center_kb.cli import KIND_DESCRIPTIONS

    assert "one of four kinds" in KIND_DESCRIPTIONS
    assert "dev" in KIND_DESCRIPTIONS


def test_noninteractive_init_error_string_is_unchanged(tmp_path: Path):
    # Frozen by contract (cli.py comment): the message still reads hub|child.
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 2
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_quickstart_dev_content(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "/dev-implement-ticket" in text
    assert "CENTER_KB_HUB_URL" in text
    assert "CENTER_KB_HTTP_TOKEN" in text
    assert "federation/registry.yaml" in text
    assert "docs/impl/" in text
    assert "cannot publish yet" in text
