from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.publish import publish

runner = CliRunner()


def test_reindex_does_not_commit_hand_edited_or_untracked_content(
    git_kb, hub_worktree, run_git
):
    publish(git_kb["kb"], str(hub_worktree), repo_id="child", mode="direct")
    tampered = hub_worktree / "federation" / "child" / "demo-doc" / "ch1-records.md"
    tampered.write_text("TAMPERED unreviewed content\n", encoding="utf-8", newline="\n")
    rogue = hub_worktree / "federation" / "rogue"
    rogue.mkdir()
    (rogue / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")

    result = runner.invoke(
        app, ["reindex", "--hub", str(hub_worktree), "--kb-dir", str(hub_worktree / ".kb")]
    )
    assert result.exit_code == 0, result.output

    committed = run_git(hub_worktree, "show", "--name-only", "--format=", "HEAD")
    assert "federation/child/demo-doc/ch1-records.md" not in committed
    assert "federation/rogue" not in committed
    head_content = run_git(
        hub_worktree, "show", "HEAD:federation/child/demo-doc/ch1-records.md"
    )
    assert "TAMPERED" not in head_content
    assert "federation/child/demo-doc/ch1-records.md" in result.output
    assert "federation/rogue" in result.output
