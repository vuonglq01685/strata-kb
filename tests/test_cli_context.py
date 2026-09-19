from typer.testing import CliRunner

from strata_kb.cli import app

runner = CliRunner()


def test_context_new_prints_block_with_head_hash(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-kb:arinc-424 §5.3",
         "--tags", "icao,airspace", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0, result.output
    assert "kb-context:" in result.output
    assert f'version: "{hub_head}"' in result.output
    assert "- arinc-kb:arinc-424 §5.3" in result.output
    assert "tags: [icao, airspace]" in result.output


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


def test_resolve_status_only_ok_prints_no_content(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    block = (
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n"
    )
    result = runner.invoke(
        app,
        ["resolve", "-", "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
        input=block,
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
    assert "Condensed: restrictive airspace" not in result.output


def test_resolve_status_only_stale_exits_2_with_reason(
    fed_hub, fixture_kb, run_git, tmp_path_factory
):
    rev1 = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend arinc-424 5.3")
    ticket = tmp_path_factory.mktemp("ticket") / "tal-3.md"
    ticket.write_text(
        f'kb-context:\n  version: "{rev1}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 2
    assert "status=stale" in result.output
    assert "!!" in result.output
    assert "NEW codes" not in result.output
    assert "designation codes" not in result.output


def test_resolve_status_only_broken_exits_1(
    fed_hub, fixture_kb, run_git, tmp_path_factory
):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    ticket = tmp_path_factory.mktemp("ticket") / "tal-4.md"
    ticket.write_text(
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "status=broken" in result.output


def _block(fed_hub, run_git, ref="arinc-kb:arinc-424 §5.3"):
    head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    return f'kb-context:\n  version: "{head}"\n  refs:\n    - {ref}\n'


def _resolve(args, fixture_kb, fed_hub, block):
    return runner.invoke(
        app, ["resolve", "-", *args, "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
        input=block,
    )


def test_write_cache_writes_the_file_and_leaves_stdout_unchanged(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "docs" / "impl" / "T-7-context.md"
    block = _block(fed_hub, run_git)
    plain = _resolve([], fixture_kb, fed_hub, block)
    result = _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output
    assert result.output == plain.output
    text = cache.read_text(encoding="utf-8")
    assert text.startswith("# Context cache — T-7\n")
    assert "<!-- kb:placeholder-map -->" in text
    assert "Condensed: restrictive airspace" in text


def test_status_only_cache_round_trip_exits_zero(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output
    assert "cache-" not in result.output
    assert "Condensed" not in result.output


def test_status_only_cache_missing_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, _block(fed_hub, run_git))
    assert result.exit_code == 1
    assert f"!! cache-missing: {cache}" in result.output


def test_status_only_cache_edited_above_the_marker_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    cache.write_text(cache.read_text(encoding="utf-8").replace("restrictive", "permissive"), encoding="utf-8")
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 1
    assert "!! cache-invalid: resolved block edited since written" in result.output


def test_status_only_cache_of_another_ticket_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    other = tmp_path / "T-8-context.md"
    _resolve(["--write-cache", str(other)], fixture_kb, fed_hub, _block(fed_hub, run_git, "icao-kb:icao-annex-2 §1.1"))
    result = _resolve(["--status-only", "--cache", str(other)], fixture_kb, fed_hub, _block(fed_hub, run_git))
    assert result.exit_code == 1
    assert "!! cache-invalid: refs differ" in result.output


def test_status_only_cache_placeholder_map_edits_are_fine(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write("| <max-alt> | 45000 | src/limits.py:12 |\n")
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output


def test_write_cache_preserves_the_map_on_regeneration(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write("| <max-alt> | 45000 | src/limits.py:12 |\n")
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    assert "| <max-alt> | 45000 |" in cache.read_text(encoding="utf-8")


def test_stale_ticket_with_a_bad_cache_exits_one_not_two(fed_hub, fixture_kb, run_git, tmp_path):
    block = _block(fed_hub, run_git)
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"), encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend")
    result = _resolve(["--status-only", "--cache", str(tmp_path / "none.md")], fixture_kb, fed_hub, block)
    assert result.exit_code == 1
    assert "status=stale" in result.output and "cache-missing" in result.output


def test_cache_flag_combinations_are_usage_errors(fed_hub, fixture_kb, run_git, tmp_path):
    block = _block(fed_hub, run_git)
    p = str(tmp_path / "c.md")
    assert _resolve(["--cache", p], fixture_kb, fed_hub, block).exit_code == 1
    assert _resolve(["--status-only", "--write-cache", p], fixture_kb, fed_hub, block).exit_code == 1
