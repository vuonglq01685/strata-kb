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
    from center_kb.federation import write_federation_index

    rev1 = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed: restrictive airspace designation codes.",
            "Condensed: restrictive airspace designation codes, amended.",
        ),
        encoding="utf-8",
    )
    # A real amendment goes through `kb publish`, which rewrites
    # federation/index.yaml with a fresh content digest alongside the
    # content -- this fixture shortcuts that by hand-editing published
    # content directly, which check_published_digests (M9) correctly cannot
    # tell apart from tampering. Re-stamp the digest so this simulates a
    # real amendment rather than a hub content integrity violation; the
    # test's actual point (a citation pinned to rev1 going stale) is
    # unaffected either way.
    write_federation_index(fed_hub / "federation")
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


def test_doctor_on_invalid_config_kind_is_a_clean_error_not_a_traceback(tmp_path):
    """H1: doctor must report an invalid config.yaml, not die producing it."""
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (kb / "config.yaml").write_text(
        "hub: " + str(tmp_path / "hub") + "\nrepo_id: child\nkind: bogus\n",
        encoding="utf-8",
        newline="\n",
    )

    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    # click's CliRunner sets result.exception to the SystemExit for ANY
    # nonzero exit (clean `typer.Exit(1)` included) -- `is None` would fail
    # even on the fix. isinstance(SystemExit) is what actually distinguishes
    # a clean exit from an uncaught ValidationError/YAMLError escaping.
    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "ValidationError" not in result.output
    assert "config.yaml" in result.output


def test_status_on_invalid_index_is_a_clean_error_not_a_traceback(tmp_path):
    """L29: kb status calls load_yaml_model unguarded — same class as H1."""
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: [unclosed\n", encoding="utf-8", newline="\n")

    result = runner.invoke(app, ["status", "--kb-dir", str(kb)])

    # See test_doctor_on_invalid_config_kind_is_a_clean_error_not_a_traceback:
    # result.exception is the SystemExit for any nonzero exit under this
    # click version, so `is None` is not the right check here.
    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 1, result.output
    assert "Traceback" not in result.output
    assert "index.yaml" in result.output
