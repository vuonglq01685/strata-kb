"""2026-10-10 review H13 and §5.2 #8: `kb doctor` names copyrighted source
files tracked by git, and a committed config.yaml carrying a hub token."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.doctor import check_config_credentials, check_source_dirs

runner = CliRunner()
SECRET = "ghs_SuperSecretToken123"


def _repo(tmp_path: Path, run_git) -> Path:
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "user.name", "t")
    run_git(tmp_path, "config", "user.email", "t@t")
    return tmp_path


def test_a_tracked_source_file_is_named(tmp_path, run_git):
    root = _repo(tmp_path, run_git)
    (root / "source").mkdir()
    (root / "source" / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    (root / "source" / "spec.pdf").write_text("x", encoding="utf-8")
    run_git(root, "add", "-f", "source/spec.pdf", "source/.gitignore")
    issues = check_source_dirs(root)
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "source/spec.pdf" in issues[0].message
    assert "git rm --cached" in issues[0].message


def test_many_tracked_files_are_capped_in_the_message(tmp_path, run_git):
    root = _repo(tmp_path, run_git)
    (root / "sources").mkdir()
    for i in range(8):
        (root / "sources" / f"d{i}.pdf").write_text("x", encoding="utf-8")
    run_git(root, "add", "sources")
    (issue,) = check_source_dirs(root)
    assert "8 file(s)" in issue.message
    assert "(+3 more)" in issue.message


def test_folders_holding_only_their_gitignore_are_silent(tmp_path, run_git):
    root = _repo(tmp_path, run_git)
    for folder in ("source", "sources"):
        (root / folder).mkdir()
        (root / folder / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
        (root / folder / "untracked.pdf").write_text("x", encoding="utf-8")
    run_git(root, "add", "-A")
    assert check_source_dirs(root) == []


def test_outside_a_git_repo_source_check_is_silent(tmp_path):
    assert check_source_dirs(tmp_path) == []


def _config(root: Path, body: str) -> Path:
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(body, encoding="utf-8")
    return kb


def test_a_tracked_config_with_a_credentialed_hub_warns_without_printing_it(
    tmp_path, run_git
):
    root = _repo(tmp_path, run_git)
    kb = _config(
        root,
        f"kind: child\nhub: https://x-access-token:{SECRET}@github.com/acme/hub.git\n"
        "repo_id: c\n",
    )
    run_git(root, "add", ".kb/config.yaml")
    (issue,) = check_config_credentials(kb, root)
    assert issue.level == "warning"
    assert "`hub:`" in issue.message
    assert "STRATA_KB_HUB" in issue.message
    assert "rotate" in issue.message
    assert SECRET not in issue.message


def test_a_credentialed_intake_url_warns_too(tmp_path, run_git):
    root = _repo(tmp_path, run_git)
    kb = _config(root, f"kind: child\nintake: https://u:{SECRET}@kb.internal\n")
    run_git(root, "add", ".kb/config.yaml")
    (issue,) = check_config_credentials(kb, root)
    assert "`intake:`" in issue.message
    assert SECRET not in issue.message


def test_an_untracked_or_clean_config_is_silent(tmp_path, run_git):
    root = _repo(tmp_path, run_git)
    kb = _config(root, f"hub: https://x-access-token:{SECRET}@github.com/a/h.git\n")
    assert check_config_credentials(kb, root) == []  # not tracked
    _config(root, "hub: https://github.com/a/h.git\n")
    run_git(root, "add", ".kb/config.yaml")
    assert check_config_credentials(kb, root) == []  # no credential


def test_kb_doctor_reports_both(git_kb, fed_hub, run_git):
    root = git_kb["root"]
    (root / "sources").mkdir()
    (root / "sources" / "manual.pdf").write_text("x", encoding="utf-8")
    run_git(root, "add", "sources/manual.pdf")
    cfg = git_kb["kb"] / "config.yaml"
    cfg.write_text(
        (cfg.read_text(encoding="utf-8") if cfg.exists() else "")
        + f"intake: https://u:{SECRET}@kb.internal\n",
        encoding="utf-8",
    )
    run_git(root, "add", ".kb/config.yaml")
    result = runner.invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(fed_hub)]
    )
    assert "sources/manual.pdf" in result.output
    assert "carries a credential" in result.output
    assert SECRET not in result.output
