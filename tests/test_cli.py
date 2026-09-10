from typer.testing import CliRunner

from center_kb.cli import app

runner = CliRunner()


def test_cli_help_shows_app_description():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "CENTER-KB" in result.output


def test_version_flag_prints_installed_version():
    import importlib.metadata

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == importlib.metadata.version("center-kb")


def test_version_flag_does_not_require_a_subcommand():
    # `app` has no_args_is_help=True; --version must short-circuit before Click
    # complains about a missing command.
    result = runner.invoke(app, ["--version"])

    assert "Missing command" not in result.output


def test_query_prints_raw_match_snippet_when_present(fed_hub, fixture_kb, monkeypatch):
    from center_kb import query as query_module
    from center_kb.query import QueryResult, SearchOutcome

    fake_results = [
        QueryResult(
            doc_id="arinc-424", section_id="5.3", title="Restrictive Airspace",
            score=1.0, citation="arinc-kb:arinc-424 §5.3", content="Condensed body.",
            tokens=5, source="arinc-kb", match_mode="keyword",
            snippet="...GRYPHON42 in raw...",
        )
    ]
    monkeypatch.setattr(
        query_module, "search_detailed",
        lambda *a, **k: SearchOutcome(results=fake_results),
    )
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 0
    assert "raw match: ...GRYPHON42 in raw..." in result.output


def test_query_omits_raw_match_line_when_snippet_empty(fed_hub, fixture_kb, monkeypatch):
    from center_kb import query as query_module
    from center_kb.query import QueryResult, SearchOutcome

    fake_results = [
        QueryResult(
            doc_id="arinc-424", section_id="5.3", title="Restrictive Airspace",
            score=1.0, citation="arinc-kb:arinc-424 §5.3", content="Condensed body.",
            tokens=5, source="arinc-kb", match_mode="keyword",
        )
    ]
    monkeypatch.setattr(
        query_module, "search_detailed",
        lambda *a, **k: SearchOutcome(results=fake_results),
    )
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 0
    assert "raw match:" not in result.output


def test_query_no_usable_terms_prints_note_to_stderr(fed_hub, fixture_kb):
    """F-C9 review round 2: neither rendering surface had a test proving a
    note actually arrives. Real (unmocked) search_detailed() call — a
    punctuation-only query tokenizes to nothing, and the CLI renders
    outcome.notes to stderr in yellow."""
    result = runner.invoke(
        app,
        [
            "query", "§§§ ---",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 0
    assert "no searchable terms" in result.stderr
    assert "no searchable terms" not in result.stdout


def test_query_index_busy_is_a_clean_error_not_a_traceback(fed_hub, fixture_kb, monkeypatch):
    """F-C2: a still-held index file must surface as a clean red message +
    exit 1, never a raw PermissionError/IndexBusyError traceback."""
    from center_kb import query as query_module
    from center_kb.searchdb import IndexBusyError

    def raise_busy(*a, **k):
        raise IndexBusyError("search index search.db is in use by another process")

    monkeypatch.setattr(query_module, "search_detailed", raise_busy)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "in use by another process" in result.output


def test_query_client_db_error_is_a_clean_error_not_a_traceback(fed_hub, fixture_kb, monkeypatch):
    """F-C2: a lost cold-build race (UNIQUE constraint) classified as a
    client error must surface as a clean red message + exit 1, never the raw
    sqlite3.IntegrityError traceback."""
    import sqlite3

    from center_kb import query as query_module

    def raise_integrity(*a, **k):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: sections.repo_id")

    monkeypatch.setattr(query_module, "search_detailed", raise_integrity)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "UNIQUE constraint failed" in result.output


def test_query_lock_db_error_still_propagates(fed_hub, fixture_kb, monkeypatch):
    """A 'lock'-classified DatabaseError is NOT a client error — it must not
    be swallowed into the clean-message branch; it keeps propagating."""
    import sqlite3

    from center_kb import query as query_module

    def raise_locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(query_module, "search_detailed", raise_locked)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 1
    assert isinstance(result.exception, sqlite3.OperationalError)


def test_query_too_many_tags_is_a_clean_error_not_a_traceback(
    fed_hub, fixture_kb, monkeypatch
):
    """F-C10: an oversized tag list surfaces from `search` as a
    `searchdb.TooManyTagsError` (`_norm_tags`'s refusal) — it must print as
    a clean red message + exit 1, never a raw traceback."""
    from center_kb import query as query_module
    from center_kb import searchdb

    def raise_too_many_tags(*a, **k):
        raise searchdb.TooManyTagsError(
            "too many tags (40000) — at most 100 are accepted"
        )

    monkeypatch.setattr(query_module, "search_detailed", raise_too_many_tags)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "too many tags" in result.output


def test_query_unrelated_value_error_still_propagates(fed_hub, fixture_kb, monkeypatch):
    """F-C10 review finding 1: `except ValueError` was too coarse —
    `pydantic.ValidationError` (raised deep in the search path when a
    federation `_manifest.yaml` is malformed: query.search ->
    _search_index -> searchdb.open_fresh -> _sync_conn -> _sync_repo ->
    models.load_yaml_model) is also a `ValueError` subclass but is NOT the
    tag-cap refusal. Only `searchdb.TooManyTagsError` gets the clean-message
    treatment; any other ValueError must keep propagating with its
    traceback intact."""
    from center_kb import query as query_module

    def raise_unrelated(*a, **k):
        raise ValueError("3 validation errors for Manifest")

    monkeypatch.setattr(query_module, "search_detailed", raise_unrelated)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 1
    assert isinstance(result.exception, ValueError)


def test_tags_lists_the_federation_vocabulary(fed_hub, fixture_kb):
    result = runner.invoke(
        app, ["tags", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert result.output.split() == ["airspace", "arinc424", "icao"]


def test_tags_on_a_kb_with_no_tags_exits_zero_with_guidance(fed_hub, fixture_kb):
    from center_kb import models

    for rid in ("arinc-kb", "icao-kb"):
        models.save_yaml_model(
            fed_hub / "federation" / rid / "index.yaml", models.KBIndex()
        )
    result = runner.invoke(
        app, ["tags", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "no tags" in result.output
    assert "kb ingest --tags" in result.output


def test_build_strict_flag_and_quality_warn_rendering(fixture_kb):
    long = " ".join(f"Sentence number {i} explains the record layout in detail." for i in range(10))
    l3 = fixture_kb / "demo-doc" / "ch1-records.raw.md"
    l3.write_text(l3.read_text(encoding="utf-8").replace(
        "Full raw text about airway records and route identifiers.", long), encoding="utf-8")
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", long), encoding="utf-8")
    soft = runner.invoke(app, ["build", "--kb-dir", str(fixture_kb)])
    assert soft.exit_code == 0 and "[warn]" in soft.output and "(quality)" in soft.output
    hard = runner.invoke(app, ["build", "--strict", "--kb-dir", str(fixture_kb)])
    assert hard.exit_code == 1 and "[error]" in hard.output and "(quality)" in hard.output


def test_stats_hints_when_tokens_never_built(fixture_kb):
    result = runner.invoke(app, ["stats", "--kb-dir", str(fixture_kb)])
    assert result.exit_code == 0
    assert "run kb build to refresh token counts" in result.output


def test_stats_omits_hint_once_tokens_are_built(fixture_kb):
    from center_kb.build import build_kb

    assert build_kb(fixture_kb).ok
    result = runner.invoke(app, ["stats", "--kb-dir", str(fixture_kb)])
    assert result.exit_code == 0
    assert "run kb build to refresh token counts" not in result.output


def test_build_bad_effort_literal_is_a_clean_error_not_a_traceback(fixture_kb):
    """B4: a pydantic.ValidationError (subclass of ValueError) from a typo'd
    `llm.effort` in index.yaml must surface as `[error] <msg>` + exit 1, not
    an unhandled traceback."""
    index_path = fixture_kb / "index.yaml"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace("effort: high", "effort: hgih"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["build", "--kb-dir", str(fixture_kb)])
    assert result.exit_code == 1
    assert not isinstance(result.exception, ValueError), result.exception
    assert "[error]" in result.output
