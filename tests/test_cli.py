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
    from center_kb.query import QueryResult

    fake_results = [
        QueryResult(
            doc_id="arinc-424", section_id="5.3", title="Restrictive Airspace",
            score=1.0, citation="arinc-kb:arinc-424 §5.3", content="Condensed body.",
            tokens=5, source="arinc-kb", match_mode="keyword",
            snippet="...GRYPHON42 in raw...",
        )
    ]
    monkeypatch.setattr(query_module, "search", lambda *a, **k: fake_results)
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
    from center_kb.query import QueryResult

    fake_results = [
        QueryResult(
            doc_id="arinc-424", section_id="5.3", title="Restrictive Airspace",
            score=1.0, citation="arinc-kb:arinc-424 §5.3", content="Condensed body.",
            tokens=5, source="arinc-kb", match_mode="keyword",
        )
    ]
    monkeypatch.setattr(query_module, "search", lambda *a, **k: fake_results)
    result = runner.invoke(
        app,
        [
            "query", "restrictive airspace",
            "--kb-dir", str(fixture_kb), "--hub", str(fed_hub),
        ],
    )
    assert result.exit_code == 0
    assert "raw match:" not in result.output


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
