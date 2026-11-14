import json

import pytest

from strata_kb import gitio, initcmd
from strata_kb.errors import KbError
from strata_kb.initcmd import expected_files, init_repo
from strata_kb.llm import AUTO_TASK_ENV
from strata_kb.upgradecmd import upgrade


def test_init_tester_scaffolds_exactly_the_tester_set(tmp_path):
    report = init_repo(tmp_path, "tester")
    assert sorted(report.created) == sorted(
        expected_files("tester") + list(initcmd.TESTER_LOCAL_OVERRIDES) + [".gitignore"]
    )


def test_tester_scaffold_has_the_contract_paths(tmp_path):
    init_repo(tmp_path, "tester")
    for rel in (
        "QUICKSTART-TESTER.md",
        "docs/test-review-rubric.md",
        "docs/test-review-rubric.local.md",
        "docs/templates/test-cases.md",
        "docs/templates/test-report.md",
        ".kb/test-env.example.yaml",
        "tests/fixtures/login.ts",
        ".github/CODEOWNERS",
        ".claude/settings.json",
        ".cursor/mcp.json",
    ):
        assert (tmp_path / rel).is_file(), rel
    assert "Polarity" in (tmp_path / "docs/templates/test-cases.md").read_text()


def test_tester_config_has_kind_and_mcp_has_playwright(tmp_path):
    init_repo(tmp_path, "tester")
    assert "kind: tester" in (tmp_path / ".kb/config.yaml").read_text()
    for rel in (".mcp.json", ".cursor/mcp.json"):
        mcp = json.loads((tmp_path / rel).read_text())
        assert set(mcp["mcpServers"]) == {"strata-kb", "playwright"}, rel


def test_tester_gitignore_hides_env_and_playwright_output(tmp_path):
    init_repo(tmp_path, "tester")
    lines = (tmp_path / ".gitignore").read_text().splitlines()
    for line in (
        ".env",
        "test-results/",
        "playwright-report/",
        ".kb/*-test/",
        ".kb/auto/",
        ".kb/runlog/",
        "tests/*/ticket.md",
    ):
        assert line in lines


def test_tester_reinit_is_idempotent_and_keeps_local_overrides(tmp_path):
    init_repo(tmp_path, "tester")
    local = tmp_path / "docs/test-review-rubric.local.md"
    local.write_text("mine\n", encoding="utf-8")
    report = init_repo(tmp_path, "tester")
    assert local.read_text(encoding="utf-8") == "mine\n"
    assert report.created == [] and report.updated == []


def test_upgrade_accepts_a_tester_repo(tmp_path, run_git, monkeypatch):
    monkeypatch.delenv(AUTO_TASK_ENV, raising=False)
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    root = tmp_path / "tester-repo"
    run_git(tmp_path, "clone", str(origin), str(root))
    run_git(root, "config", "user.name", "t")
    run_git(root, "config", "user.email", "t@t")
    run_git(root, "config", "commit.gpgsign", "false")
    init_repo(root, "tester")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    run_git(root, "push", "-u", "origin", "HEAD")
    run_git(root, "remote", "set-head", "origin", gitio.current_branch(root))
    assert upgrade(root, open_pr=False).branch is None


def test_upgrade_still_refuses_other_kinds(tmp_path, run_git, monkeypatch):
    monkeypatch.delenv(AUTO_TASK_ENV, raising=False)
    root = tmp_path / "hub"
    root.mkdir()
    run_git(root, "init")
    init_repo(root, "hub")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    with pytest.raises(KbError, match="ba, dev or tester"):
        upgrade(root, open_pr=False)
