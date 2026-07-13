from pathlib import Path

import pytest
from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.initcmd import expected_files, init_repo

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


def test_init_does_not_overwrite_config(tmp_path):
    from center_kb.initcmd import init_repo

    init_repo(tmp_path, "hub")
    cfg = tmp_path / ".kb" / "config.yaml"
    cfg.write_text("hub: /my/hub\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub")
    assert ".kb/config.yaml" in report.skipped
    assert cfg.read_text(encoding="utf-8") == "hub: /my/hub\n"


def test_kb_doctor_on_fresh_skeleton_requires_hub(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["doctor", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 1
    assert "config.yaml" in result.output


def test_cli_init_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb ingest" in result.output
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "skipped" in result2.output
    assert "0 created" in result2.output
    assert "0 updated" in result2.output
    assert "2 skipped" in result2.output


def test_cli_init_updates_stale_scaffold(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path)])
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    skill.write_text("stale\n", encoding="utf-8")
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "updated" in result.output
    assert "stale" not in skill.read_text(encoding="utf-8")


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
    assert "kb docker-setup" not in child_q
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
