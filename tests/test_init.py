from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.initcmd import EXPECTED_FILES, init_repo

runner = CliRunner()


def test_init_creates_all_files(tmp_path: Path):
    report = init_repo(tmp_path)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert report.skipped == []
    for rel in EXPECTED_FILES:
        assert (tmp_path / rel).is_file(), rel


def test_init_is_idempotent_never_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: keep-me, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path)
    assert report.created == []
    assert sorted(report.skipped) == sorted(EXPECTED_FILES)
    assert "keep-me" in marker.read_text(encoding="utf-8")


def test_init_force_overwrites(tmp_path: Path):
    init_repo(tmp_path)
    marker = tmp_path / ".kb" / "index.yaml"
    marker.write_text("docs: [{id: gone, title: X}]\n", encoding="utf-8")
    report = init_repo(tmp_path, force=True)
    assert sorted(report.created) == sorted(EXPECTED_FILES)
    assert "gone" not in marker.read_text(encoding="utf-8")


def test_kb_doctor_passes_on_fresh_skeleton(tmp_path: Path):
    init_repo(tmp_path)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(tmp_path / ".kb")])
    assert result.exit_code == 0
    assert "kb doctor: OK" in result.output


def test_cli_init_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb ingest" in result.output
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "skipped" in result2.output


def test_quickstart_uses_correct_ingest_flag(tmp_path: Path):
    init_repo(tmp_path)
    text = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "--id" in text
    assert "--doc-id" not in text


def test_init_scaffolds_ai_integration_files(tmp_path: Path):
    init_repo(tmp_path)
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
    init_repo(tmp_path)
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
    init_repo(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md"
    prompt = tmp_path / ".github" / "prompts" / "kb-publish.prompt.md"
    assert skill.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-publish" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "NEVER run `kb approve` or `kb publish`" in text  # hard rule
        assert "kb diff" in text
        assert "kb status" in text
        assert "CENTER_KB_HUB" in text
        assert "kb doctor" in text


def test_quickstart_and_instructions_have_cli_reference(tmp_path: Path):
    init_repo(tmp_path)
    quick = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (quick, instr):
        assert "## CLI reference" in text
        # every kb command appears
        for cmd in (
            "kb init", "kb ingest", "kb summarize", "kb status", "kb build",
            "kb query", "kb get", "kb stats", "kb diff", "kb approve",
            "kb publish", "kb resolve", "kb doctor",
        ):
            assert cmd in text, cmd
        assert "--level l2|l3" in text
        assert "l1|l2|l3" not in text
    assert "/kb-ingest" in quick
    assert "/kb-publish" in quick


def test_kb_summarize_templates_have_prose_only_rules(tmp_path: Path):
    init_repo(tmp_path)
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (skill, instr):
        assert "Summarize the prose ONLY" in text
        assert "Table-only section:" in text


def test_kb_summarize_skill_is_parallel_orchestrator(tmp_path: Path):
    init_repo(tmp_path)
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
