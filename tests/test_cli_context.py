from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_context_new_prints_block_with_head_hash(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-kb:arinc-424 §5.3",
         "--tags", "demo,airspace", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0, result.output
    assert "kb-context:" in result.output
    assert f'version: "{hub_head}"' in result.output
    assert "- arinc-kb:arinc-424 §5.3" in result.output
    assert "tags: [demo, airspace]" in result.output


def test_context_new_rejects_unresolvable_ref(fed_hub, fixture_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §9.9",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "9.9" in result.output


def test_context_new_rejects_empty_refs(fed_hub, fixture_kb):
    result = runner.invoke(
        app,
        ["context", "new", "--refs", ",,", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "is empty" in result.output
    assert "kb-context:" not in result.stdout


def test_resolve_reads_block_from_file(fed_hub, fixture_kb, run_git, tmp_path_factory):
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

    ticket = tmp_path_factory.mktemp("ticket") / "tal-1.md"
    ticket.write_text(
        f'kb-context:\n  version: "{rev1}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n    - icao-kb:icao-annex-2 §1.1\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 2  # has stale (arinc-424 §5.3), not broken
    assert "status=stale" in result.output
    assert "status=ok" in result.output


def test_resolve_broken_exits_1(fed_hub, fixture_kb, run_git, tmp_path_factory):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    ticket = tmp_path_factory.mktemp("ticket") / "tal-2.md"
    ticket.write_text(
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n    - arinc-kb:arinc-424 §9.9\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["resolve", str(ticket), "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 1
    assert "status=broken" in result.output


def test_resolve_missing_file_exits_1_without_traceback(git_kb, tmp_path_factory):
    missing = tmp_path_factory.mktemp("ticket") / "does-not-exist.md"
    result = runner.invoke(
        app, ["resolve", str(missing), "--kb-dir", str(git_kb["kb"])]
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "could not read file" in result.output
    assert str(missing) in result.output


def test_resolve_stdin(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    block = (
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n'
        "    - icao-kb:icao-annex-2 §1.1\n"
    )
    result = runner.invoke(
        app, ["resolve", "-", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
        input=block,
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
