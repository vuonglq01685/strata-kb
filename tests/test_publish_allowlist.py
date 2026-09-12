from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.publish import publish

runner = CliRunner()


def test_config_yaml_and_dotfiles_never_reach_the_hub(git_kb, hub_worktree, run_git):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text(
        'hub: "https://x-access-token:ghs_SECRET@github.com/org/kb-hub.git"\n',
        encoding="utf-8",
        newline="\n",
    )
    (kb / ".env").write_text("AWS_SECRET_ACCESS_KEY=AKIAEXAMPLE\n", encoding="utf-8")
    (kb / "demo-doc" / "ch1-records.md.bak").write_text("stray\n", encoding="utf-8")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: config + stray files")

    report = publish(kb, str(hub_worktree), repo_id="child", mode="direct")

    entry = hub_worktree / "federation" / "child"
    assert not (entry / "config.yaml").exists()
    assert not (entry / ".env").exists()
    assert not (entry / "demo-doc" / "ch1-records.md.bak").exists()
    assert (entry / "index.yaml").exists()
    assert (entry / "demo-doc" / "ch1-records.md").exists()
    assert report.skipped == [".env", "config.yaml", "demo-doc/ch1-records.md.bak"]


def test_an_already_mirrored_config_is_removed_on_the_next_publish(
    git_kb, hub_worktree, run_git
):
    """F-D9 finding 6 false-pass fix: this used to pass with publish.py's
    allowlist filter reverted, because the git_kb fixture has no
    .kb/config.yaml at all -- absent from the child, "config.yaml" was
    classified as deleted by plain hash-diff mirror semantics regardless of
    whether the allowlist ran, so the test never actually exercised it. The
    child must itself hold a config.yaml, with DIFFERENT content from the
    leaked hub-side copy, so that pre-fix the file is RE-MIRRORED (content
    differs -> "changed") on the next publish instead of deleted."""
    (git_kb["kb"] / "config.yaml").write_text(
        "hub: https://real-hub.example/kb-hub.git\n", encoding="utf-8", newline="\n"
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: add its own config.yaml")

    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    leaked = hub_worktree / "federation" / "child" / "config.yaml"
    leaked.write_text("hub: secret\n", encoding="utf-8", newline="\n")
    run_git(hub_worktree, "add", "-A")
    run_git(hub_worktree, "commit", "-m", "hub: an old version mirrored config.yaml")

    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Records\n\nEdited.\n", encoding="utf-8", newline="\n"
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: edit")
    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")

    assert not leaked.exists()


def test_cli_publish_prints_the_skip_warning(git_kb, hub_worktree, run_git):
    """F-D9 finding 6: cli._echo_publish_report's `[warn] ... allowlist ...`
    line (report.skipped) had no coverage -- reverting it still passed the
    48-test wave set."""
    (git_kb["kb"] / "config.yaml").write_text(
        "hub: https://real-hub.example/kb-hub.git\n", encoding="utf-8", newline="\n"
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "child: add config.yaml")

    result = runner.invoke(
        app,
        ["publish", "--hub", str(hub_worktree), "--repo-id", "child",
         "--kb-dir", str(git_kb["kb"]), "--direct"],
    )
    assert result.exit_code == 0
    assert "[warn]" in result.output
    assert "allowlist" in result.output
    assert "config.yaml" in result.output
