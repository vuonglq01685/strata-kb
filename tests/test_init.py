import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from strata_kb import initcmd
from strata_kb.cli import app
from strata_kb.initcmd import expected_files, init_repo
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


def test_scaffolded_federation_readme_describes_the_full_mirror(tmp_path: Path):
    # Fix round 1, Minor 5: the three assertions this test used to run were
    # a weak trip-wire — reviewer-measured, one of the three
    # ("Content (L2/L3) stays in the child repo") could never fail because
    # the old template wrapped that phrase mid-line and the raw substring
    # never existed either way. Normalize whitespace first so a reflow
    # can't itself false-fail, then pin the claims that actually carry the
    # governance behaviour, plus a real trip-wire that matches the old
    # (pre-full-mirror) template text as it actually wrapped.
    dest = tmp_path / "hub"
    dest.mkdir()
    initcmd.init_repo(dest, "hub")
    text = (dest / "federation" / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    assert "L0" in text and "L3" in text
    assert "only holds the child's catalog and summaries" not in normalized
    assert "Content (L2/L3) stays in the child repo" not in normalized
    assert "federation/registry.yaml" in normalized
    assert "governed" in normalized
    assert "refuses direct pushes" in normalized
    assert "branch protection" in normalized
    assert "_meta.yaml" in normalized
    # Note on braces (informational): initcmd._render uses a plain
    # str.replace, not str.format, so a literal `{`/`}` in a template is
    # safe and does not need escaping. This assertion is cheap insurance
    # against an accidental stray placeholder, not a correctness
    # requirement of the renderer.
    assert "{" not in text and "}" not in text


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
    assert sorted(report.skipped) == sorted(
        [".kb/index.yaml", ".kb/config.yaml", ".gitignore"]
    )
    assert ".claude/skills/kb-summarize/SKILL.md" in report.updated
    assert "keep-me" in index.read_text(encoding="utf-8")
    assert "stale skill content" not in skill.read_text(encoding="utf-8")


def test_init_is_idempotent_when_already_current(tmp_path: Path):
    init_repo(tmp_path, "hub")
    report = init_repo(tmp_path, "hub")
    assert report.created == []
    assert report.updated == []
    assert sorted(report.skipped) == sorted(
        [".kb/index.yaml", ".kb/config.yaml", ".gitignore"]
    )


def test_init_force_overwrites_protected_data(tmp_path: Path):
    init_repo(tmp_path, "hub")
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: gone, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub", force=True)
    assert report.created == []
    assert ".kb/index.yaml" in report.updated
    # .gitignore is merge-only under every mode (R18) — already carries the
    # `.kb-work/` line from the first init, so force leaves it alone and
    # reports it as skipped rather than silently ignoring it.
    assert report.skipped == [".gitignore"]
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
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
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
    assert "3 skipped" in result2.output


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
    assert result.exit_code == 1
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_cli_init_conflicting_kind_errors(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path), "--kind", "child"])
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 1
    assert "already initialized as 'child'" in result.output
    # nothing was scaffolded as hub
    assert not (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt(tmp_path: Path, monkeypatch):
    from strata_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="hub\n")
    assert result.exit_code == 0
    assert "Central knowledge hub" in result.output      # description shown
    assert "Authoring repo" in result.output
    assert (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt_rejects_invalid_then_accepts(
    tmp_path: Path, monkeypatch
):
    from strata_kb import cli

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
    assert "--print-prompt" in skill_text      # never restates writing rules
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
        assert "STRATA_KB_HUB" in text
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
    assert "${STRATA_KB_HUB_URL}/mcp" in text
    assert "Bearer ${STRATA_KB_HTTP_TOKEN}" in text


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


def test_kb_summarize_templates_use_print_prompt_workflow(tmp_path: Path):
    init_repo(tmp_path, "hub")
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (skill, instr):
        assert "kb summarize <doc-id> --print-prompt" in text
        assert "no LLM needed" in text


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
    assert "kb summarize <doc-id> --print-prompt" in rule_text
    assert "no LLM needed" in rule_text


def test_init_scaffolds_cursor_mcp_per_kind(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    hub_mcp = (hub_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "strata_kb.mcp" in hub_mcp                      # stdio, same as .mcp.json
    assert hub_mcp == (hub_repo / ".mcp.json").read_text(encoding="utf-8")
    child_mcp = (child_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "${env:STRATA_KB_HUB_URL}/mcp" in child_mcp     # Cursor env syntax
    assert "Bearer ${env:STRATA_KB_HTTP_TOKEN}" in child_mcp


def test_assistant_slash_command_parity(tmp_path: Path):
    """Every kb-* command exists for Claude, Copilot, and Cursor in each kind."""
    common = ["kb-ingest", "kb-publish", "kb-summarize", "kb-init"]
    layouts = {
        "claude": lambda n: (
            Path(".claude/commands") / f"{n}.md"
            if n in ("kb-summarize", "kb-docker-setup", "kb-approve", "kb-mcp-setup")
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
    # kb-mcp-setup is a reader-kind command: the hub serves MCP over stdio
    # and has nothing to connect to.
    for kind, names in (("hub", common), ("child", common + ["kb-mcp-setup"])):
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
    assert "--print-prompt" in skill                 # never restates writing rules
    assert '"l2_summary"' in skill
    assert '"l1_summary"' in skill
    assert "batches of ~5" in skill                  # granularity
    assert "at most 10" in skill                     # concurrency cap
    assert "kb build --allow-pending --strict" in skill  # per-wave verify
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
    from strata_kb import config as config_mod

    assert config_mod.load_config(tmp_path).asset_store.mode == "s3"


def test_record_asset_store_appends_none_block(tmp_path: Path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("kind: hub\n", encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "none") == "recorded"
    from strata_kb import config as config_mod

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
    assert result.exit_code == 1
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
    ".gitattributes",
    ".github/instructions/kb-summarize.instructions.md",
    ".github/prompts/kb-approve.prompt.md",
    ".github/prompts/kb-docker-setup.prompt.md",
    ".github/prompts/kb-ingest.prompt.md",
    ".github/prompts/kb-init.prompt.md",
    ".github/prompts/kb-publish.prompt.md",
    ".github/workflows/kb-publish.yml",
    ".gitignore",
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
    ".gitattributes",
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
    # Two more entries than expected_files("ba") on purpose: the
    # review-rubric/ac-quality `.local.md` stubs are create-once BA repo
    # data (Task 11, MEDIUM-5) and deliberately NOT in the template map
    # `expected_files` reads from — see initcmd.BA_LOCAL_OVERRIDES. Sorted
    # as ONE combined list (not two sorted lists concatenated): the
    # `.local.md` paths interleave alphabetically with the base `docs/`
    # entries (e.g. "docs/ac-quality.local.md" < "docs/ac-quality.md"),
    # so concatenating two separately-sorted lists would not equal the
    # single globally-sorted `report.created`.
    assert sorted(report.created) == sorted(
        expected_files("ba") + list(initcmd.BA_LOCAL_OVERRIDES)
    )
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


# --- Task 11 (MEDIUM-5): `.local.md` overrides for the BA rubric -----------
# Same create-once contract as `conventions.scaffold_conventions`'s
# `docs/conventions/<lang>.local.md` (C11): the BASE files
# (docs/review-rubric.md, docs/ac-quality.md) stay package-owned and keep
# being refreshed by `kb init`; only the `.local.md` overrides are written
# once and never touched again.


def test_ba_init_creates_the_local_override_stubs(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    assert (tmp_path / "docs" / "review-rubric.local.md").is_file()
    assert (tmp_path / "docs" / "ac-quality.local.md").is_file()


def test_ba_reinit_never_touches_a_local_override(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    local = tmp_path / "docs" / "review-rubric.local.md"
    local.write_text(
        "# our own criteria\n- [ ] cites an AIP\n", encoding="utf-8"
    )
    before = local.read_bytes()

    report = initcmd.init_repo(tmp_path, "ba")

    assert local.read_bytes() == before
    assert any(
        "local overrides — never refreshed" in entry
        for entry in report.skipped
    )


def test_ba_reinit_still_refreshes_the_base_rubric(tmp_path):
    initcmd.init_repo(tmp_path, "ba")
    base = tmp_path / "docs" / "review-rubric.md"
    base.write_text("clobbered\n", encoding="utf-8")

    initcmd.init_repo(tmp_path, "ba")

    assert "Maturity review rubric" in base.read_text(encoding="utf-8")


def test_init_rejects_unknown_kind_still_excludes_ba_typos(tmp_path: Path):
    with pytest.raises(ValueError):
        init_repo(tmp_path, "BA")


def test_hub_child_unchanged_by_phase4(tmp_path: Path):
    assert sorted(expected_files("hub")) == sorted(_PRE_PHASE4_HUB_FILES)
    # child gained exactly the four kb-mcp-setup wrappers since Phase 4 —
    # named explicitly rather than folded into the frozen list, so the
    # freeze keeps meaning "Phase 4/5 added nothing".
    assert sorted(expected_files("child")) == sorted(
        _PRE_PHASE4_CHILD_FILES + _MCP_SETUP_WRAPPERS
    )
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
    assert "pip install strata-kb" in content
    assert "kb ticket lint" in content
    assert "vars.STRATA_KB_HUB" in content
    assert "secrets.KB_HUB_TOKEN" in content
    # no hardcoded credential/URL — only GH Actions expressions
    assert "kb.internal" not in content
    assert "example.com" not in content
    assert "ghp_" not in content  # no literal token-shaped string


def test_quickstart_ba_content(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = (tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8")
    assert "pip install strata-kb" in text
    assert "STRATA_KB_HUB_URL" in text
    assert "STRATA_KB_HTTP_TOKEN" in text
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


def test_cli_init_local_override_skip_has_no_force_hint(tmp_path: Path):
    """Task 11 review Important 1: `--force` cannot touch a `.local.md`
    override (scaffold_ba_local_overrides takes no `force` parameter and
    the call site passes none), so the CLI must not tell a BA it can.
    A genuinely protected file's skip line still carries the hint.
    """
    runner.invoke(app, ["init", str(tmp_path), "--kind", "ba"])
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "ba"])
    assert result.exit_code == 0
    lines = result.output.splitlines()
    local_lines = [ln for ln in lines if "review-rubric.local.md" in ln]
    assert local_lines, result.output
    assert "--force" not in local_lines[0], local_lines[0]
    protected_lines = [ln for ln in lines if ln.strip().startswith("skipped") and ".kb/config.yaml" in ln]
    assert protected_lines, result.output
    assert "--force" in protected_lines[0], protected_lines[0]


def test_cli_init_assets_rejected_for_ba(tmp_path: Path):
    result = runner.invoke(
        app, ["init", str(tmp_path), "--kind", "ba", "--assets", "s3"]
    )
    assert result.exit_code == 1
    assert "hub" in result.output


def test_resolve_kind_interactive_accepts_ba(tmp_path: Path, monkeypatch):
    from strata_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="ba\n")
    assert result.exit_code == 0
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert text.count("kind: ba") == 1
    assert (tmp_path / "QUICKSTART-BA.md").exists()


def test_resolve_kind_interactive_rejects_invalid_then_accepts_ba(
    tmp_path: Path, monkeypatch
):
    from strata_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="server\nba\n")
    assert result.exit_code == 0
    assert (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8").count(
        "kind: ba"
    ) == 1


def test_resolve_kind_interactive_accepts_dev(tmp_path: Path, monkeypatch):
    from strata_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="dev\n")
    assert result.exit_code == 0
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert text.count("kind: dev") == 1
    assert (tmp_path / "QUICKSTART-DEV.md").exists()


def test_resolve_kind_interactive_rejects_invalid_then_accepts_dev(
    tmp_path: Path, monkeypatch
):
    from strata_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="server\ndev\n")
    assert result.exit_code == 0
    # Pins the new error string: dropping "dev" from the accepted tuple
    # would reject it interactively forever while every other assertion in
    # this file stays green, so the four-kind list itself is the needle.
    assert "'hub', 'child', 'ba', 'dev'" in result.output
    assert (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8").count(
        "kind: dev"
    ) == 1


def test_config_load_accepts_kind_ba(tmp_path: Path):
    from strata_kb.config import load_config

    kb_dir = tmp_path / ".kb"
    kb_dir.mkdir()
    (kb_dir / "config.yaml").write_text("kind: ba\nhub: ''\n", encoding="utf-8")
    cfg = load_config(kb_dir)
    assert cfg.kind == "ba"


def test_ba_kind_scaffolds_the_mission_plan_set(tmp_path):
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

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
    from strata_kb import mission
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")

    for rel in _MISSION_WRAPPER_PATHS:
        text = (tmp_path / rel).read_text(encoding="utf-8").lower()
        assert "never auto-generate" in text, rel
        assert "never auto-pick" in text, rel


def test_ci_gate_covers_both_tickets_and_missions(tmp_path):
    from strata_kb.initcmd import init_repo

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
    from strata_kb.initcmd import init_repo

    init_repo(tmp_path, "ba")
    wf_path = tmp_path / ".github" / "workflows" / "kb-ticket-lint.yml"
    assert wf_path.is_file()
    wf = wf_path.read_text(encoding="utf-8")
    assert "name: kb-ticket-lint" in wf
    assert "\n  lint:\n" in wf


def test_ci_gate_has_no_hardcoded_credentials(tmp_path):
    from strata_kb.initcmd import init_repo

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
    "import json, os, sys\n"
    "argv = sys.argv[1:]\n"
    "log = os.environ.get('KB_STUB_LOG')\n"
    "if log:\n"
    "    with open(log, 'a', encoding='utf-8') as fh:\n"
    "        fh.write('\\t'.join(argv) + '\\n')\n"
    "fail_markers = [m for m in os.environ.get('KB_STUB_FAIL', '').split(os.pathsep) if m]\n"
    "failed = any(a in fail_markers for a in argv)\n"
    # Task 13 review (Important 1): _hub_or_exit can exit before --json ever
    # writes a report at all (unreachable hub) -- it prints a plain-text
    # message to stdout instead. KB_STUB_NONJSON reproduces that exit shape
    # for a given path so the dispatch step's non-JSON-tolerant parsing can
    # be exercised without a real hub.
    "nonjson_markers = [m for m in os.environ.get('KB_STUB_NONJSON', '').split(os.pathsep) if m]\n"
    "if any(a in nonjson_markers for a in argv):\n"
    "    print('hub unreachable: could not resolve strata-kb-hub.example')\n"
    "    sys.exit(1)\n"
    # Task 13 review (Important 2): the stub used to only ever exit 0/1, so
    # the dispatch step's rc==2 -> STALE branch never actually ran under
    # test. KB_STUB_RC lets a failing run pin a specific exit code.
    "rc = int(os.environ.get('KB_STUB_RC', '1'))\n"
    # Task 13 (MEDIUM-6): the real dispatch step always passes --json and
    # parses the report for its step-summary table, so the stub must emit
    # the same {pass, errors, warnings, notes} shape kb ticket/mission lint
    # --json actually produces (lintcore.LintReport.to_json), or the
    # dispatch step's own `json.load` blows up on empty/missing output.
    "if '--json' in argv:\n"
    "    print(json.dumps({\n"
    "        'pass': not failed,\n"
    "        'errors': ['stub configured to fail'] if failed else [],\n"
    "        'warnings': [],\n"
    "        'notes': [],\n"
    "    }))\n"
    "sys.exit(rc if failed else 0)\n"
)


def _write_python_shim(bindir: Path) -> None:
    """The dispatch step's `python -` heredoc (Task 13, MEDIUM-6) relies on
    a bare `python` on PATH — guaranteed on a real GitHub Actions runner by
    `actions/setup-python`, but not on every dev box (macOS ships only
    `python3`). Shim it in the same bindir the `kb` stub already lives in,
    so these hermetic subprocess tests don't depend on the host's PATH."""
    bindir.mkdir(parents=True, exist_ok=True)
    shim = bindir / "python"
    shim.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8", newline="\n"
    )
    shim.chmod(shim.stat().st_mode | 0o111)


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
    _write_python_shim(bindir)
    log_path = tmp_path / "kb.log"

    base_env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "BASE_REF": "main",
        "STRATA_KB_HUB": "https://example.invalid/hub",
        "KB_STUB_LOG": str(log_path),
        "RUNNER_TEMP": str(tmp_path),
        # Real GitHub Actions always provides this; the dispatch step now
        # writes its per-file summary table there (Task 13, MEDIUM-6).
        "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md"),
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
    # Trailing `--json` (Task 13, MEDIUM-6): the dispatch step now always
    # requests a machine-readable report for its step-summary table.
    assert (
        "mission\tlint\tmissions/M-Đăng-nhập.md\t--hub\thttps://example.invalid/hub\t--json"
        in log_lines
    )
    assert (
        "ticket\tlint\ttickets/T-new.md\t--hub\thttps://example.invalid/hub\t--json"
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
    # Task 13 review (Important 2): the failure must be annotated on the
    # failing file and pinned in the step-summary table with an error count.
    assert (
        "::error file=tickets/T-new.md::stub configured to fail" in result.stderr
    )
    summary = (tmp_path / "step-summary.md").read_text(encoding="utf-8")
    assert "| `tickets/T-new.md` | FAIL | 1 | 0 |" in summary


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
            "STRATA_KB_HUB": "https://example.invalid/hub",
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
            "STRATA_KB_HUB": "https://example.invalid/hub",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md"),
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
    _write_python_shim(bindir)
    log_path = tmp_path / "kb-synthetic.log"

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BASE_REF": "main",
            "STRATA_KB_HUB": "https://example.invalid/hub",
            "KB_STUB_LOG": str(log_path),
            "KB_STUB_FAIL": "",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(tmp_path / "step-summary.md"),
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


@_needs_bash
def test_ci_gate_dispatch_loop_pins_stale_verdict(tmp_path):
    """Task 13 review (Important 2): the `kb` stub used to only ever exit
    0/1, so the dispatch step's `rc == 2 -> STALE` branch never actually ran
    under test. KB_STUB_RC lets the stub exit 2 to exercise it end to end."""
    run_script = _extract_lint_dispatch_script(tmp_path)
    script_path = tmp_path / "lint-step-stale.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo-stale"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    (repo / "tickets").mkdir()
    (repo / "tickets" / "base.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tickets/base.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    (repo / "tickets" / "T-stale.md").write_text("stale\n", encoding="utf-8")
    _git(repo, "add", "tickets/T-stale.md")
    _git(repo, "commit", "-q", "-m", "pr: add ticket")

    bindir = tmp_path / "bin-stale"
    write_cli_stub(bindir, "kb", _KB_STUB_BODY)
    _write_python_shim(bindir)
    log_path = tmp_path / "kb-stale.log"
    summary_path = tmp_path / "step-summary-stale.md"

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BASE_REF": "main",
            "STRATA_KB_HUB": "https://example.invalid/hub",
            "KB_STUB_LOG": str(log_path),
            "KB_STUB_FAIL": "tickets/T-stale.md",
            "KB_STUB_RC": "2",
            "KB_FAIL_ON_STALE": "1",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    summary = summary_path.read_text(encoding="utf-8")
    assert "| `tickets/T-stale.md` | STALE | 1 | 0 |" in summary
    # The dispatch script forwards KB_FAIL_ON_STALE as --fail-on-stale
    # (kb-ticket-lint.yml ~127-128) — pin that it actually reaches the CLI.
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    stale_line = next(
        line for line in log_lines if "tickets/T-stale.md" in line
    )
    assert "--fail-on-stale" in stale_line


@_needs_bash
def test_ci_gate_dispatch_loop_survives_a_non_json_lint_exit(tmp_path):
    """Important 1 (task-13 review): `_hub_or_exit` (cli.py) can exit before
    `kb ticket lint --json` ever writes a JSON report -- e.g. an unreachable
    private hub prints a plain-text message to stdout and exits 1. The
    dispatch step's `python - ... <<PY` heredoc used to `json.load` that
    non-JSON output unguarded: the traceback made the heredoc itself exit
    non-zero, which (under `bash -e`) aborted the whole step mid-loop --
    `cat`/`::endgroup::` never ran and every later file was silently never
    linted. KB_STUB_NONJSON reproduces the exit shape without a real hub.
    """
    run_script = _extract_lint_dispatch_script(tmp_path)
    script_path = tmp_path / "lint-step-nonjson.sh"
    script_path.write_text(run_script, encoding="utf-8")

    repo = tmp_path / "repo-nonjson"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.example")
    _git(repo, "config", "user.name", "t")
    (repo / "tickets").mkdir()
    (repo / "tickets" / "base.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "tickets/base.md")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    # 'A-broken' sorts before 'Z-after' so `git diff --name-only` (tree
    # order) hands the broken file to the loop first -- proving the second
    # file is reached only if the loop survives the first one's crash.
    (repo / "tickets" / "A-broken.md").write_text("a\n", encoding="utf-8")
    (repo / "tickets" / "Z-after.md").write_text("z\n", encoding="utf-8")
    _git(repo, "add", "tickets/A-broken.md", "tickets/Z-after.md")
    _git(repo, "commit", "-q", "-m", "pr: add two tickets")

    bindir = tmp_path / "bin-nonjson"
    write_cli_stub(bindir, "kb", _KB_STUB_BODY)
    _write_python_shim(bindir)
    log_path = tmp_path / "kb-nonjson.log"
    summary_path = tmp_path / "step-summary-nonjson.md"

    result = subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=repo,
        env={
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
            "BASE_REF": "main",
            "STRATA_KB_HUB": "https://example.invalid/hub",
            "KB_STUB_LOG": str(log_path),
            "KB_STUB_NONJSON": "tickets/A-broken.md",
            "RUNNER_TEMP": str(tmp_path),
            "GITHUB_STEP_SUMMARY": str(summary_path),
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    # The raw non-JSON message still reaches the log.
    assert "hub unreachable" in result.stdout
    assert "::endgroup::" in result.stdout
    summary = summary_path.read_text(encoding="utf-8")
    assert "| `tickets/A-broken.md` | FAIL | 1 | 0 |" in summary
    assert (
        "::error file=tickets/A-broken.md::lint exited without a JSON report"
        in result.stderr
    )
    # The loop did not short-circuit: the file after the broken one was
    # still linted.
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert any("tickets/Z-after.md" in line for line in log_lines)


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
    # Pin the count too: comparing expected_files("dev") to itself lets a
    # premature extra row slip in unnoticed on both sides of the equality.
    # 27 (Stage A) + 4 (dev-code-seed's own four-way wrappers) + 12 (the
    # reused kb-summarize/kb-approve/kb-publish rows the seed flow needs,
    # Stage C) + 1 (.claude/settings.json, the usage Stop hook) + 1
    # (docs/impl/.gitignore — C1 keeps the context cache out of git) + 3
    # (batch 7: the PR template, its workflow, and the TDD exemption doc) + 1
    # (Wave G fix round 2 Minor 1: .gitattributes, the same F-D10 exemption
    # a child repo gets) + 4 (the kb-mcp-setup wrappers, MCP_CLIENT_TEMPLATES)
    # = 53.
    assert len(expected_files("dev")) == 53
    assert sorted(report.created) == sorted(expected_files("dev"))
    assert report.skipped == []
    for rel in _DEV_STAGE_A_PATHS:
        assert (tmp_path / rel).is_file(), rel


def test_init_kind_dev_scaffolds_the_child_gitattributes_exemption(tmp_path: Path):
    """Minor 1 (Wave G fix round 2): a dev repo publishes .kb/ (its own
    source knowledge) exactly like a child does, but DEV_TEMPLATES carried
    no .gitattributes entry at all -- neither the CRLF-normalisation
    exemption a child gets, nor any exemption of its own -- reopening F-D10
    on a Windows dev machine."""
    init_repo(tmp_path, "dev")
    text = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert text.rstrip().splitlines()[-1] == ".kb/** -text"


def test_init_child_gitattributes_ends_with_the_kb_exemption(tmp_path: Path):
    """Important 1 (mutants MU10/MU10b): the child scaffold's own
    .gitattributes carrying `.kb/** -text` last, and CHILD_TEMPLATES
    pointing at the CHILD resource rather than the hub's own (which ends
    `federation/** -text` instead), both survived the full suite with no
    test pinning the child scaffold's actual content."""
    init_repo(tmp_path, "child")
    text = (tmp_path / ".gitattributes").read_text(encoding="utf-8")
    assert text.rstrip().splitlines()[-1] == ".kb/** -text"


def test_init_kind_dev_gitignores_the_context_cache(tmp_path: Path):
    init_repo(tmp_path, "dev")
    gi = (tmp_path / "docs" / "impl" / ".gitignore").read_text(encoding="utf-8")
    assert "*-context.md" in gi


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
    assert sorted(expected_files("hub")) == sorted(_PRE_PHASE4_HUB_FILES)
    assert sorted(expected_files("child")) == sorted(
        _PRE_PHASE4_CHILD_FILES + _MCP_SETUP_WRAPPERS
    )
    for rel in expected_files("ba"):
        assert "dev-" not in rel, rel


def test_config_accepts_kind_dev(tmp_path: Path):
    from strata_kb.config import load_config

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
    from strata_kb.cli import KIND_DESCRIPTIONS

    assert "one of four kinds" in KIND_DESCRIPTIONS
    assert "dev" in KIND_DESCRIPTIONS


def test_noninteractive_init_error_string_is_unchanged(tmp_path: Path):
    # Frozen by contract (cli.py comment): the message still reads hub|child.
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 1
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_quickstart_dev_content(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "/dev-implement-ticket" in text
    assert "STRATA_KB_HUB_URL" in text
    assert "STRATA_KB_HTTP_TOKEN" in text
    assert "federation/registry.yaml" in text
    assert "docs/impl/" in text
    # Task D2: Stage C shipped `dev-code-seed` + `kb svc note` on this
    # branch, so `<repo_id>-svc` is no longer "not available yet" — that
    # interim claim is now false and was cleared (README R2 sibling fix).
    # Assert the corrected, present-tense framing instead.
    assert "`<repo_id>-svc`) is not available yet" not in text
    # Fix round 1, Minor 4: `"curated" in text.lower()` pins nothing —
    # any document containing that one word passes. Pin the actual
    # corrected sentence instead.
    assert "Curated responsibility knowledge" in text


def test_quickstart_dev_documents_the_auto_merge_policy(tmp_path: Path):
    # Task review, Important 8: the plan never said where the auto-merge
    # policy is documented; the shipped README pointed at "that hub's own
    # setup", which doesn't exist anywhere. Spec Sec11 says it belongs in
    # QUICKSTART-DEV -- this asserts it is actually there, not just
    # claimed to be.
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "auto-merg" in text.lower()
    assert "hub-side branch-protection" in text


def test_init_kind_dev_scaffolds_the_code_workflow(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert (tmp_path / ".github" / "workflows" / "kb-code.yml").is_file()
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()


def test_kb_code_workflow_is_not_on_hub_child_or_ba(tmp_path: Path):
    for kind in ("hub", "child", "ba"):
        assert ".github/workflows/kb-code.yml" not in expected_files(kind), kind


# --- Phase 5 Stage C: dev-code-seed + the reused authoring wrappers --------


def test_init_kind_dev_scaffolds_dev_code_seed_and_the_reused_wrappers(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert (tmp_path / ".claude" / "skills" / "dev-code-seed" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "commands" / "dev-code-seed.md").is_file()
    assert (tmp_path / ".github" / "prompts" / "dev-code-seed.prompt.md").is_file()
    assert (tmp_path / ".cursor" / "commands" / "dev-code-seed.md").is_file()
    # reused authoring wrappers the seed flow needs
    for name in ("kb-summarize", "kb-approve"):
        assert (tmp_path / ".claude" / "skills" / name / "SKILL.md").is_file(), name
        assert (tmp_path / ".claude" / "commands" / f"{name}.md").is_file(), name
        assert (tmp_path / ".cursor" / "commands" / f"{name}.md").is_file(), name
    assert (tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md").is_file()
    assert (tmp_path / ".cursor" / "commands" / "kb-publish.md").is_file()
    assert (tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "kb-summarize.mdc").is_file()


def test_init_kind_dev_still_excludes_ingest_and_the_child_publish_workflow(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert not (tmp_path / ".claude" / "skills" / "kb-ingest").exists()
    assert not (tmp_path / ".claude" / "skills" / "kb-docker-setup").exists()
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()
    assert not (tmp_path / "source").exists()
    # kb-publish has no Claude command file anywhere in the package
    assert not (tmp_path / ".claude" / "commands" / "kb-publish.md").exists()


# --- Task D2: docs, QUICKSTART updates, release ----------------------------


def test_quickstart_dev_documents_the_seed_and_service_history(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "/dev-code-seed" in text
    assert "kb svc note" in text
    assert "-code" in text and "-svc" in text
    assert "auto-merge" in text
    assert "10-15 min" in text or "10–15 min" in text


def test_quickstart_ba_points_at_code_knowledge(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = (tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8")
    assert "-code" in text
    assert "-svc" in text
    # Fix round 1, Minor 5 (plan-mandated): `"-code" in text` is satisfied
    # by any mention of `kb-code.yml`, and neither original assertion
    # touched the new section's own load-bearing strings. Pin those.
    assert "Code knowledge on the hub" in text
    assert "%%TODO: verify against codebase%%" in text


def test_quickstart_dev_documents_the_redo_consequence(tmp_path: Path):
    # Fix round 1, Minor 6 (pins R3 — the `kb summarize --redo` truth this
    # branch fought over across four review passes). `--redo` is not a
    # blanket data-loss event (the accrued `hist.*` history survives) but
    # it genuinely is one for a service's human-corrected responsibility
    # prose, which is gone from L2/the manifest summary and recoverable
    # only from git, not from `kb summarize` itself.
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "for the accrued ticket history" in text
    assert "come back only from git" in text
    # Fix round 1 follow-up (same false-claim class, caught by a sibling
    # task's reviewer while verifying its own fix to the dev-code-seed
    # wrappers): `cli.py:570-586` shows `kb summarize --redo` does not
    # stop at the reset — it re-summarizes in the same invocation.
    assert "re-summarizes in the same command" in text
    assert "goes back to `pending`" not in text
    # Fix round 2, Minor 2: "never stuck at `pending`" (this test's own
    # prior pin) was itself a false absolute — summarize.py:230-236
    # leaves a section whose LLM call fails at `pending`
    # (cli.py:591-596: "Some sections stay pending"). The verified
    # claude-skill-dev-code-seed.md:77 model makes no end-status promise
    # at all; matched that here too. Ban the disproven absolute instead
    # of re-pinning a replacement one.
    assert "never stuck at `pending`" not in text


def test_quickstart_dev_documents_the_first_run_stale_risk_warning(tmp_path: Path):
    # Fix round 1, Minor 6 (pins R4 — the first `--scaffold-svc` run after
    # this release will flag every already-`reviewed` svc.* section as
    # stale-risk purely from the tables:/files: L3 relabel, not from any
    # real code change).
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "even though nothing in your code changed" in text


def test_quickstart_dev_states_the_stale_risk_comparison_precisely(tmp_path: Path):
    # Final review, Minor 6: `core.py:1130` compares `.strip()`-ed L3
    # bodies, not literal bytes, and not "any" change either -- a change
    # of nothing but leading/trailing whitespace does not flag. "byte-
    # for-byte" and the bare "**Any** change" overstate that by exactly
    # the whitespace-trim case; state the comparison precisely instead.
    # Whitespace-normalised (`" ".join(text.split())`) the same way
    # test_templates.py's `_normalised` matches hand-wrapped prose --
    # this two-word needle spans a line break in the actual file.
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    normalised = " ".join(text.split())
    assert "byte-for-byte" not in normalised
    assert "whole-body, whitespace-trimmed" in normalised


def test_quickstart_dev_orients_the_reused_kb_summarize_wrapper(tmp_path: Path):
    # Fix round 1, Minor 6 (pins R5 — the reused `kb-summarize` wrapper's
    # own "after `kb ingest`" wording is false on a `dev` repo; readers
    # must be told to read it as `kb code-ingest --scaffold-svc` instead).
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "read every `kb ingest` mention in that wrapper as" in text


def test_quickstart_ba_documents_the_tag_lint_break(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    # The break itself, the fix, and the lookup — all three, or a BA hits a
    # red lint with no way out.
    assert "v0.19.0 makes an unknown `kb-context` tag a lint error" in text
    assert "delete the tag from the block" in text
    assert "never re-run `kb context new`" in text
    assert "kb tags" in text


def test_quickstart_ba_documents_that_tags_are_derived(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    assert "tags are derived from the documents your refs pin" in text


# --- Phase 5 (kb usage measurement): the Stop hook scaffold ------------------


def test_settings_json_is_scaffolded_for_ba_and_dev(tmp_path: Path):
    for kind in ("ba", "dev"):
        target = tmp_path / kind
        init_repo(target, kind)
        settings = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for group in settings["hooks"]["Stop"]
            for hook in group["hooks"]
        ]
        assert commands == ["kb usage ingest-transcript --hook-stdin"], kind


def test_settings_json_is_not_scaffolded_for_hub_or_child(tmp_path: Path):
    # A hub or child repo authors no tickets, so every row would be
    # unattributed — 0.6s per turn for noise.
    for kind in ("hub", "child"):
        assert ".claude/settings.json" not in expected_files(kind), kind


def test_settings_json_is_protected_from_a_second_init(tmp_path: Path):
    # initcmd overwrites any file outside PROTECTED_FILES, and a dev's own
    # hooks live in this file.
    init_repo(tmp_path, "dev")
    path = tmp_path / ".claude" / "settings.json"
    path.write_text('{"hooks": {}, "mine": true}', encoding="utf-8")

    report = init_repo(tmp_path, "dev")

    assert ".claude/settings.json" in report.skipped
    assert json.loads(path.read_text(encoding="utf-8"))["mine"] is True


def test_quickstart_ba_documents_the_usage_hook(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    assert "kb usage report" in text
    assert "adds about 0.6s per turn" in text
    assert "kb usage ingest-transcript" in text
    # The ledger is the record; the HTML is derived. Someone who commits the
    # HTML and edits it has edited nothing that survives the next report run.
    assert "generated, not a record" in text


def test_quickstart_dev_documents_the_usage_hook(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = " ".join((tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8").split())
    assert "kb usage report" in text
    assert "adds about 0.6s per turn" in text


def test_quickstarts_document_the_ingest_errors_log(tmp_path: Path):
    # _usage_log_error's own docstring calls this file the ONLY diagnostic
    # channel a silent Stop hook has; a QUICKSTART that never names it leaves
    # a dev with no way to discover why the ledger isn't growing.
    for kind, fname in (("ba", "QUICKSTART-BA.md"), ("dev", "QUICKSTART-DEV.md")):
        target = tmp_path / kind
        init_repo(target, kind)
        text = (target / fname).read_text(encoding="utf-8")
        assert ".kb/usage/ingest-errors.log" in text, kind


def test_quickstarts_force_clause_names_all_three_protected_files(tmp_path: Path):
    # The pre-branch text said '--force overwrites them too' (all protected
    # files); the rewrite named only settings.json after '--force', losing
    # "too"'s antecedent — and --force really does replace .kb/config.yaml
    # (kind, repo_id, asset_store) too, so the warning undersold the risk.
    for kind, fname in (("ba", "QUICKSTART-BA.md"), ("dev", "QUICKSTART-DEV.md")):
        target = tmp_path / kind
        init_repo(target, kind)
        text = " ".join((target / fname).read_text(encoding="utf-8").split())
        assert "--force` replaces all three outright" in text, kind


def test_quickstarts_state_the_hooks_version_floor(tmp_path: Path):
    # An older kb has no `usage` command, so the hook exits 2 -- and a Stop hook
    # exiting 2 blocks the turn instead of failing quietly, with nothing in
    # ingest-errors.log because the failure precedes `kb usage` entirely.
    for kind, name in (("ba", "QUICKSTART-BA.md"), ("dev", "QUICKSTART-DEV.md")):
        target = tmp_path / kind
        init_repo(target, kind)
        text = " ".join((target / name).read_text(encoding="utf-8").split())
        assert "must be 0.19.0 or newer" in text, kind
        assert "blocks the turn from ending" in text, kind


def test_quickstarts_document_the_reingest_repair(tmp_path: Path):
    # The repair path that actually works: delete the file and re-ingest, which
    # is safe because a call already in the ledger is skipped.
    for kind, name in (("ba", "QUICKSTART-BA.md"), ("dev", "QUICKSTART-DEV.md")):
        target = tmp_path / kind
        init_repo(target, kind)
        text = " ".join((target / name).read_text(encoding="utf-8").split())
        assert "Re-ingesting is always safe" in text, kind
        assert "kb usage ingest-transcript" in text, kind


# --- Batch 5 (D conventions pack): dev-kind post-step -----------------------


def test_init_dev_scaffolds_conventions_for_detected_language(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    report = init_repo(tmp_path, "dev")
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()
    assert (tmp_path / "docs" / "conventions" / "python.local.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "coding-python.mdc").is_file()
    assert (
        tmp_path / ".github" / "instructions" / "coding-python.instructions.md"
    ).is_file()
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("<!-- kb:conventions -->")
    assert "docs/conventions/python.md" in report.created
    assert "CLAUDE.md" in report.created
    # only the detected language
    assert not (tmp_path / "docs" / "conventions" / "ts.md").exists()


def test_init_dev_reinit_preserves_local_conventions_and_user_claude_md(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    init_repo(tmp_path, "dev")
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    local.write_text("my overrides\n", encoding="utf-8")
    claude = tmp_path / "CLAUDE.md"
    user_text = "# My notes\n" + claude.read_text(encoding="utf-8")
    claude.write_text(user_text, encoding="utf-8")
    base = tmp_path / "docs" / "conventions" / "python.md"
    base.write_text("stale\n", encoding="utf-8")
    # --force must refresh the base but STILL not touch local or CLAUDE.md
    report = init_repo(tmp_path, "dev", force=True)
    assert local.read_text(encoding="utf-8") == "my overrides\n"
    assert claude.read_text(encoding="utf-8") == user_text  # marker present
    assert "stale" not in base.read_text(encoding="utf-8")
    assert (
        "docs/conventions/python.local.md (local overrides — never refreshed)"
        in report.skipped
    )


def test_init_dev_without_manifests_notes_and_skips_conventions(tmp_path: Path):
    report = init_repo(tmp_path, "dev")
    assert not (tmp_path / "docs" / "conventions").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert any("no language manifests detected" in n for n in report.notes)


def test_expected_files_unchanged_by_conventions_pack():
    # conventions are a post-step, never template-map rows (spec: Scope/Out)
    for kind in ("hub", "child", "ba", "dev"):
        assert not any("conventions" in rel for rel in expected_files(kind))
        assert "CLAUDE.md" not in expected_files(kind)


def test_init_non_dev_kinds_gain_no_conventions(tmp_path: Path):
    for kind in ("hub", "child", "ba"):
        repo = tmp_path / kind
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        init_repo(repo, kind)
        assert not (repo / "docs" / "conventions").exists(), kind
        assert not (repo / "CLAUDE.md").exists(), kind


def _tiering_section(text: str) -> str:
    start = text.index("## Model tiering")
    rest = text.index("\n## ", start + 1)
    return text[start:rest]


def test_quickstarts_document_model_tiering(tmp_path: Path):
    for kind, quickstart in (("dev", "QUICKSTART-DEV.md"), ("ba", "QUICKSTART-BA.md")):
        target = tmp_path / kind
        target.mkdir()
        init_repo(target, kind)
        section = _tiering_section((target / quickstart).read_text(encoding="utf-8"))
        assert "usage-prices.yaml" in section, kind
        assert "effective_date" in section, kind
        # The caveat is the load-bearing sentence: without it the advice
        # raises the bill while everyone believes it lowers it.
        assert "discards the prompt cache" in section, kind
        assert "2x at 1h" in section, kind
        assert "can cost **more** than not tiering" in section, kind
        # And it must say how to check rather than asking for trust.
        assert "kb usage report" in section, kind


def test_model_tiering_names_no_model_ids(tmp_path: Path):
    # The decision this pins: tiers are abstract here, and the model names
    # live only in the price table, which carries an effective_date and warns
    # when it is stale. A name copied into prose has no such guard.
    for kind, quickstart in (("dev", "QUICKSTART-DEV.md"), ("ba", "QUICKSTART-BA.md")):
        target = tmp_path / kind
        target.mkdir()
        init_repo(target, kind)
        section = _tiering_section((target / quickstart).read_text(encoding="utf-8"))
        for banned in ("claude-opus-", "claude-sonnet-", "claude-haiku-"):
            assert banned not in section, f"{kind}: {banned}"


# --- Batch 7 (E1 + E2): the PR gate is scaffolded for kind dev only --------

_BATCH7_DEV_PATHS = (
    ".github/pull_request_template.md",
    ".github/workflows/kb-pr-lint.yml",
    "docs/tdd-exemptions.md",
)


def test_init_kind_dev_scaffolds_the_pr_gate(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for rel in _BATCH7_DEV_PATHS:
        assert (tmp_path / rel).is_file(), rel


def test_the_pr_gate_is_not_scaffolded_for_other_kinds():
    for kind in ("hub", "child", "ba"):
        for rel in _BATCH7_DEV_PATHS:
            assert rel not in expected_files(kind), f"{kind}: {rel}"


def test_the_shipped_pr_template_fails_the_linter(tmp_path: Path):
    # The proof that the comment-stripping rule is real. An author who
    # deletes nothing and writes nothing must get a red check, not a green
    # one — if this ever passes, the gate has become decoration.
    from strata_kb.prlint import lint_body

    init_repo(tmp_path, "dev")
    text = (tmp_path / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )
    report = lint_body(text)
    assert not report.passed
    assert {f.code for f in report.errors} == {"empty-section"}


def test_hub_scaffold_ignores_the_search_index(tmp_path):
    """Reviewer C F-C17: the index lives at <hub>/.kb-work/search.db and shows
    up as untracked `?? .kb-work/`. No init scaffold covered it, so a hub
    maintainer running `git add -A` commits a multi-MB binary."""
    from strata_kb import initcmd

    initcmd.init_repo(tmp_path, "hub")
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".kb-work/" in text


def test_hub_gitignore_is_protected_from_a_second_init(tmp_path: Path):
    # A hub's own .gitignore may carry secret-exclusion rules (.env,
    # credentials) a maintainer added — a routine re-init must not silently
    # destroy them (F-C17 review round 2, Critical). R18 (final-branch
    # review, Critical): the same must hold under --force too — `kb init
    # --kind hub --force` must never wholesale-overwrite the file (that
    # would un-ignore a bearer token `kb docker setup` already wrote to
    # .env), so .gitignore is merge-only regardless of force.
    init_repo(tmp_path, "hub")
    path = tmp_path / ".gitignore"
    path.write_text(".kb-work/\n.env\n", encoding="utf-8")

    report = init_repo(tmp_path, "hub")

    assert ".gitignore" in report.skipped
    assert ".env" in path.read_text(encoding="utf-8")
    assert ".kb-work/" in path.read_text(encoding="utf-8")

    report = init_repo(tmp_path, "hub", force=True)
    assert ".gitignore" in report.skipped
    assert ".env" in path.read_text(encoding="utf-8")
    assert ".kb-work/" in path.read_text(encoding="utf-8")


def test_hub_gitignore_missing_kb_work_line_gets_it_appended(tmp_path: Path):
    # A hub .gitignore predating F-C17 (or hand-edited without the line) must
    # gain `.kb-work/` on re-init without losing the maintainer's own rules —
    # under both default and --force (R18).
    init_repo(tmp_path, "hub")
    path = tmp_path / ".gitignore"
    path.write_text(".env\ncredentials.json\n", encoding="utf-8")

    report = init_repo(tmp_path, "hub")

    assert ".gitignore" in report.updated
    text = path.read_text(encoding="utf-8")
    assert ".env" in text
    assert "credentials.json" in text
    assert ".kb-work/" in text.splitlines()

    # Idempotent: a second run (even with force) finds the line and skips.
    report2 = init_repo(tmp_path, "hub", force=True)
    assert ".gitignore" in report2.skipped
    text2 = path.read_text(encoding="utf-8")
    assert ".env" in text2
    assert "credentials.json" in text2


def test_hub_non_utf8_gitignore_is_left_untouched_not_crashed(tmp_path: Path):
    # Final-review fix #1 follow-up: PowerShell 5.1's `echo x > .gitignore`
    # writes UTF-16LE. Plain `kb init --kind hub` (no --force) must not
    # traceback on it and must not rewrite/transcode a file it could not
    # read — mirrors doctor.check_hub's guard.
    init_repo(tmp_path, "hub")
    path = tmp_path / ".gitignore"
    raw = ".env\n".encode("utf-16")
    path.write_bytes(raw)

    report = init_repo(tmp_path, "hub")

    assert ".gitignore" in report.skipped
    assert ".gitignore" not in report.updated
    assert path.read_bytes() == raw
    assert any(".gitignore" in n for n in report.notes)
    # The rest of the scaffold still completes after the guarded file.
    assert (tmp_path / "QUICKSTART.md").exists()

    report2 = init_repo(tmp_path, "hub", force=True)
    assert ".gitignore" in report2.skipped
    assert path.read_bytes() == raw


def _pyproject_version() -> str:
    # Deliberately independent of `strata_kb.__version__`/importlib.metadata —
    # this must be a source _render's implementation cannot also be reading,
    # or a regression there would go undetected (mirrors
    # scripts/check_package.py's pyproject_version()).
    root = Path(__file__).resolve().parent.parent
    for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.startswith("version ="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("`version =` not found in pyproject.toml")


def test_scaffolded_workflows_pin_the_scaffolding_version(tmp_path):
    from strata_kb import initcmd

    expected_version = _pyproject_version()
    # Regression guard: `__init__.py` once hand-maintained a stale
    # `__version__ = "0.1.0"` that never matched pyproject.toml — a scaffold
    # pinned to that would fail at `pip install` for every child. This must
    # never come back silently.
    assert expected_version != "0.1.0"

    dest = tmp_path / "child"
    dest.mkdir()
    initcmd.init_repo(dest, "child")
    wf = (dest / ".github" / "workflows" / "kb-publish.yml").read_text(encoding="utf-8")
    assert f"pip install strata-kb=={expected_version}" in wf
    assert "pip install strata-kb\n" not in wf
    compose = (dest / "docker-compose.yml").read_text(encoding="utf-8")
    assert ":latest" not in compose
    # release.yml only ever pushes vX.Y.Z tags (docker-release retags the
    # verified sha- build to ${GITHUB_REF_NAME}, the v* tag that triggered
    # the release) plus `latest` and `sha-<commit>` — a bare
    # `strata-kb:<version>` tag has never existed on GHCR. Assert the shape
    # that is actually published, and that the unpublished bare form isn't
    # what got rendered instead.
    assert f"strata-kb:v{expected_version}" in compose
    assert f"strata-kb:{expected_version}" not in compose


# H2 (Wave H round 5): the version test above is a *string* check, so an edit
# that leaves the image tag alone but deletes something else the file has to
# carry passes it untouched -- which is exactly what happened: round 4's
# mem_limit edit removed the `volumes:` block from the hub template and from
# the repo-root docker-compose.yml (the child template kept its), both files
# still rendered, and nothing failed. The two tests below extend the pinning
# shape from "the template pins a version" to "the template still declares
# what it has to mount", parsed as YAML rather than grepped, so a future edit
# cannot silently drop a mount either.

_HUB_MOUNTS = ["./:/data", "kb-model-cache:/home/app/.cache"]


def _compose_services(text: str) -> dict:
    doc = yaml.safe_load(text)
    assert isinstance(doc, dict) and doc.get("services"), text
    return doc


def _assert_no_dangling_volumes(doc: dict, label: str) -> None:
    """Every named volume a service mounts is declared top-level, and every
    top-level declaration is actually mounted by some service. `docker
    compose config` accepts a file that fails both halves -- an orphan
    declaration renders fine and does nothing, which is how `kb-model-cache`
    survived the deletion of the mount that referenced it."""
    declared = set(doc.get("volumes") or {})
    mounted = set()
    for svc in doc["services"].values():
        for mount in svc.get("volumes") or []:
            source = mount.split(":", 1)[0]
            # a bind mount's source is a path, not a named volume
            if not source.startswith((".", "/", "~")):
                mounted.add(source)
    assert mounted <= declared, f"{label}: mounts an undeclared volume {mounted - declared}"
    assert declared <= mounted, f"{label}: declares an unmounted volume {declared - mounted}"


def test_scaffolded_compose_pins_the_hub_data_and_model_volumes(tmp_path):
    """A hub that renders is not a hub that works: Dockerfile runs
    `WORKDIR /data` and serves `--kb /data/.kb --hub /data`, so a hub
    compose without `./:/data` boots against an EMPTY knowledge base in
    container-local scratch, and one without the model cache re-downloads
    the embedding model on every restart."""
    from strata_kb import initcmd

    dest = tmp_path / "hub"
    dest.mkdir()
    initcmd.init_repo(dest, "hub")
    doc = _compose_services((dest / "docker-compose.yml").read_text(encoding="utf-8"))
    mounts = doc["services"]["hub"].get("volumes")
    assert mounts is not None, "scaffolded hub compose declares no volumes at all"
    for want in _HUB_MOUNTS:
        assert want in mounts, f"scaffolded hub compose lost {want!r}"
    _assert_no_dangling_volumes(doc, "scaffolded hub")


def test_child_compose_keeps_its_volumes_and_the_root_compose_matches_the_hub_template(
    tmp_path,
):
    """The child template kept its mounts through round 4 -- pin that too, so
    the asymmetry cannot invert. The repo's own docker-compose.yml is the
    same deployment shape as the hub template and lost the same two mounts in
    the same edit, so the two are asserted together: this is the only test
    that reads a compose file as YAML, and keeping them apart is how they
    drifted."""
    from strata_kb import initcmd

    dest = tmp_path / "child"
    dest.mkdir()
    initcmd.init_repo(dest, "child")
    child = _compose_services((dest / "docker-compose.yml").read_text(encoding="utf-8"))
    for want in _HUB_MOUNTS:
        assert want in child["services"]["hub"]["volumes"], f"child compose lost {want!r}"
    _assert_no_dangling_volumes(child, "scaffolded child")

    root = Path(__file__).resolve().parent.parent / "docker-compose.yml"
    doc = _compose_services(root.read_text(encoding="utf-8"))
    for want in _HUB_MOUNTS:
        assert want in doc["services"]["hub"]["volumes"], f"root compose lost {want!r}"
    _assert_no_dangling_volumes(doc, "repo-root")


def test_no_template_leaves_an_unfilled_version_placeholder(tmp_path):
    from strata_kb import initcmd

    for kind in ("hub", "child", "ba", "dev"):
        dest = tmp_path / kind
        dest.mkdir()
        initcmd.init_repo(dest, kind)
        for path in dest.rglob("*"):
            if path.is_file() and path.suffix in {".yml", ".yaml"}:
                assert "{version}" not in path.read_text(encoding="utf-8")


from importlib.metadata import version as _dist_version


@pytest.mark.parametrize(
    ("kind", "workflow"),
    [("ba", "kb-ticket-lint.yml"), ("dev", "kb-pr-lint.yml")],
)
def test_scaffolded_workflows_pin_the_cli(tmp_path, kind, workflow):
    initcmd.init_repo(tmp_path, kind)
    text = (tmp_path / ".github" / "workflows" / workflow).read_text(
        encoding="utf-8"
    )
    assert f"pip install strata-kb=={_dist_version('strata-kb')}" in text
    assert "{version}" not in text


def test_hub_and_child_scaffolds_pin_lf_line_endings(tmp_path):
    from strata_kb import initcmd

    for kind in ("hub", "child"):
        dest = tmp_path / kind
        dest.mkdir()
        initcmd.init_repo(dest, kind)
        text = (dest / ".gitattributes").read_text(encoding="utf-8")
        assert "* text=auto eol=lf" in text


# --- Task 12: depth-3 detection and `kb init --lang` (M7) -------------------


def test_init_dev_lang_scaffolds_the_pack_records_it_and_reinit_reuses_it(tmp_path: Path):
    init_repo(tmp_path, "dev", langs=["python"])
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert "langs: [python]" in (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    (tmp_path / "docs" / "conventions" / "python.md").unlink()
    report = init_repo(tmp_path, "dev")   # plain re-init, no flag
    assert "docs/conventions/python.md" in report.created


def test_init_cli_rejects_an_unknown_lang(tmp_path: Path):
    from typer.testing import CliRunner

    from strata_kb.cli import app

    result = CliRunner().invoke(app, ["init", str(tmp_path), "--kind", "dev", "--lang", "cobol"])
    assert result.exit_code == 1
    assert "cobol" in result.output and "python" in result.output
    assert not (tmp_path / ".kb").exists()


# --- Task 12 fix round 1: validate recorded langs; note an already-recorded
# `langs:` when --lang can't change it (append-only) -------------------------


def test_init_dev_drops_unknown_recorded_langs_and_notes_them(tmp_path: Path):
    init_repo(tmp_path, "dev")
    cfg = tmp_path / ".kb" / "config.yaml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8") + "langs: [nodejs, python]\n", encoding="utf-8"
    )
    report = init_repo(tmp_path, "dev")
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()
    assert not (tmp_path / "docs" / "conventions" / "nodejs.md").exists()
    assert any("nodejs" in n for n in report.notes)


def test_init_dev_lang_notes_when_langs_already_recorded(tmp_path: Path):
    init_repo(tmp_path, "dev", langs=["python"])
    report = init_repo(tmp_path, "dev", langs=["java"])
    assert (tmp_path / "docs" / "conventions" / "java.md").is_file()
    assert "langs: [python]" in (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert any("hand-edit" in n and "python" in n for n in report.notes)


_MCP_SETUP_WRAPPERS = [
    ".claude/skills/kb-mcp-setup/SKILL.md",
    ".claude/commands/kb-mcp-setup.md",
    ".github/prompts/kb-mcp-setup.prompt.md",
    ".cursor/commands/kb-mcp-setup.md",
]


@pytest.mark.parametrize("kind", ["child", "ba", "dev"])
def test_mcp_setup_wrappers_exist_on_every_reader_kind(tmp_path: Path, kind):
    init_repo(tmp_path, kind)
    for rel in _MCP_SETUP_WRAPPERS:
        assert (tmp_path / rel).is_file(), (kind, rel)


def test_mcp_setup_wrappers_are_absent_on_the_hub(tmp_path: Path):
    init_repo(tmp_path, "hub")
    for rel in _MCP_SETUP_WRAPPERS:
        assert not (tmp_path / rel).exists(), rel


def test_mcp_setup_wrappers_never_take_the_token_in_chat(tmp_path: Path):
    """The assistant runs in a non-TTY subprocess, so the hidden prompt is
    unavailable; asking in chat would put a live credential in the
    transcript. Every wrapper must say so and must send the user to their
    own terminal."""
    init_repo(tmp_path, "child")
    for rel in _MCP_SETUP_WRAPPERS:
        text = (tmp_path / rel).read_text(encoding="utf-8")
        if rel.endswith(".claude/commands/kb-mcp-setup.md"):
            continue  # the thin Claude command only delegates to the skill
        assert "NEVER ask for the token" in text, rel
        assert "their own terminal" in text, rel
        assert "kb mcp-setup --hub-url" in text, rel
