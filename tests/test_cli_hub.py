from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_context_new_with_hub_ref_pins_hub_version(git_kb, hub_worktree, run_git, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §5.3",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert f'hub_version: "{hub_head}"' in result.output


def test_context_new_local_only_has_no_hub_version(git_kb, hub_worktree, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "demo-doc §1.1",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "hub_version" not in result.output


def test_context_new_bad_hub_ref_exit_1(git_kb, hub_worktree, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §9.9",
         "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 1


def test_resolve_cli_with_hub(git_kb, hub_worktree, run_git, tmp_path, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    ticket = tmp_path / "ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{git_kb["rev2"]}"\n'
        f'  hub_version: "{hub_head}"\n  refs:\n    - arinc-424 §5.3\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(git_kb["kb"]),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
    assert "status=ok" in result.output


def test_doctor_context_with_hub(git_kb, hub_worktree, run_git, tmp_path, monkeypatch):
    monkeypatch.chdir(git_kb["root"])
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    ticket = tmp_path / "ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{git_kb["rev2"]}"\n'
        f'  hub_version: "{hub_head}"\n  refs:\n    - arinc-424 §5.3\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--kb-dir", str(git_kb["kb"]), "--context", str(ticket),
         "--hub", str(hub_worktree)],
    )
    assert result.exit_code == 0, result.output
