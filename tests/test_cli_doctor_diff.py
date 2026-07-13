from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_diff_shows_changed_section(git_kb):
    result = runner.invoke(
        app,
        ["diff", "demo-doc", "--against", git_kb["rev1"], "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "~ §1.1" in result.output


def test_diff_unknown_doc_exits_1(git_kb):
    result = runner.invoke(
        app, ["diff", "missing-doc", "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1


def test_doctor_clean_kb(git_kb, fed_hub):
    result = runner.invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0
    assert "OK" in result.output


def test_doctor_broken_kb_exits_1(git_kb, fed_hub):
    (git_kb["kb"] / "demo-doc" / "ch1-records.raw.md").unlink()
    result = runner.invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 1
    assert "[error]" in result.output


def test_doctor_context_stale_exits_2(git_kb, fed_hub, run_git, tmp_path_factory):
    rev1 = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed: restrictive airspace designation codes.",
            "Condensed: restrictive airspace designation codes, amended.",
        ),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend arinc-424 5.3")

    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f'kb-context:\n  version: "{rev1}"\n  refs:\n    - arinc-kb:arinc-424 §5.3\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"]),
         "--hub", str(fed_hub)],
    )
    assert result.exit_code == 2
    assert "[warning]" in result.output


def test_doctor_context_broken_exits_1(git_kb, fed_hub, run_git, tmp_path_factory):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    ticket = tmp_path_factory.mktemp("t") / "tal.md"
    ticket.write_text(
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n    - arinc-kb:arinc-424 §9.9\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["doctor", "--context", str(ticket), "--kb-dir", str(git_kb["kb"]),
         "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
