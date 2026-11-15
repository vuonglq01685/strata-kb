"""`reportfetch` — a published test report read back from the hub."""

from __future__ import annotations

from importlib import resources

import pytest
from typer.testing import CliRunner

from strata_kb import reportfetch
from strata_kb.cli import app
from tests.test_testflow import STORY, _text, publish_tests

runner = CliRunner()


def test_render_latest_round_with_provenance(plan_hub):
    publish_tests(
        plan_hub.root,
        "tester-one",
        STORY,
        _text(STORY, 1, "FAIL"),
        _text(STORY, 2, "FAIL"),
    )
    n, text = reportfetch.render(plan_hub, STORY)
    assert n == 2 and f"§{STORY}.R2" in text and "do not edit" in text
    assert "> Fetched from hub: tester-one:tester-one-test " in text
    assert text.startswith("# R2")
    assert reportfetch.rounds(plan_hub, STORY) == [1, 2]


def test_render_round_and_unknown_round(plan_hub):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    assert reportfetch.render(plan_hub, STORY, 1)[0] == 1
    with pytest.raises(reportfetch.ReportFetchError, match="R1"):
        reportfetch.render(plan_hub, STORY, 5)


def test_no_report_and_unsafe_story(plan_hub):
    with pytest.raises(reportfetch.ReportFetchError):
        reportfetch.render(plan_hub, STORY)
    with pytest.raises(reportfetch.ReportFetchError):
        reportfetch.render(plan_hub, "../x")


def test_assets_copied_only_when_referenced_and_regular(plan_hub):
    sha = "a" * 64
    other = "b" * 64
    text = _text(STORY, 1, "FAIL").replace(
        "staging, seed a.", f"seed a ![](assets/{sha}.png)"
    )
    publish_tests(plan_hub.root, "tester-one", STORY, text)
    folder = next(plan_hub.root.glob("federation/**/tester-one-test"))
    (folder / "assets").mkdir()
    (folder / "assets" / f"{sha}.png").write_bytes(b"png")
    (folder / "assets" / f"{other}.png").write_bytes(b"x")  # unreferenced
    got, missing = reportfetch.assets_of(plan_hub, STORY, 1)
    assert [p.name for p in got] == [f"{sha}.png"] and missing == []


def _hub_with_image(plan_hub):
    sha = "a" * 64
    text = _text(STORY, 1, "FAIL").replace(
        "staging, seed a.", f"seed a ![](assets/{sha}.png)"
    )
    publish_tests(plan_hub.root, "tester-one", STORY, text)
    folder = next(plan_hub.root.glob("federation/**/tester-one-test"))
    return f"{sha}.png", folder


def test_assets_missing_from_clone_are_reported(plan_hub):
    name, _ = _hub_with_image(plan_hub)
    assert reportfetch.assets_of(plan_hub, STORY, 1) == ([], [name])


def test_symlinked_asset_file_is_missing(plan_hub, tmp_path):
    name, folder = _hub_with_image(plan_hub)
    (folder / "assets").mkdir()
    (tmp_path / "secret.png").write_bytes(b"s")
    (folder / "assets" / name).symlink_to(tmp_path / "secret.png")
    assert reportfetch.assets_of(plan_hub, STORY, 1) == ([], [name])


def test_symlinked_assets_dir_holds_nothing(plan_hub, tmp_path):
    name, folder = _hub_with_image(plan_hub)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / name).write_bytes(b"s")
    (folder / "assets").symlink_to(tmp_path / "out")
    assert reportfetch.assets_of(plan_hub, STORY, 1) == ([], [name])


def _invoke(plan_hub, tmp_path, monkeypatch, *args):
    monkeypatch.chdir(tmp_path)
    return runner.invoke(app, ["report", "fetch", *args, "--hub", str(plan_hub.root)])


def test_cli_writes_child_dir(plan_hub, tmp_path, monkeypatch):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    result = _invoke(plan_hub, tmp_path, monkeypatch, STORY, "--child", f"{STORY}.web")
    assert result.exit_code == 0, result.output
    path = tmp_path / "docs" / "impl" / f"{STORY}.web" / "report-R1.md"
    assert path.is_file() and "report-R1.md" in result.output
    assert "do not edit" in path.read_text(encoding="utf-8")


def test_cli_default_dir_is_story_and_out_overrides(plan_hub, tmp_path, monkeypatch):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    assert _invoke(plan_hub, tmp_path, monkeypatch, STORY).exit_code == 0
    assert (tmp_path / "docs" / "impl" / STORY / "report-R1.md").is_file()
    res = _invoke(plan_hub, tmp_path, monkeypatch, STORY, "--out", str(tmp_path / "o"))
    assert res.exit_code == 0 and (tmp_path / "o" / "report-R1.md").is_file()


def test_cli_warns_on_missing_asset(plan_hub, tmp_path, monkeypatch):
    name, _ = _hub_with_image(plan_hub)
    result = _invoke(plan_hub, tmp_path, monkeypatch, STORY)
    assert result.exit_code == 0, result.output
    assert f"warning: assets/{name} is not in the hub clone" in result.output
    assert (tmp_path / "docs/impl" / STORY / "report-R1.md").is_file()


def test_cli_unsafe_child_writes_nothing(plan_hub, tmp_path, monkeypatch):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    result = _invoke(plan_hub, tmp_path, monkeypatch, STORY, "--child", "../x")
    assert result.exit_code == 1
    assert not (tmp_path / "docs").exists() and not (tmp_path / "x").exists()


def test_cli_unknown_round_writes_nothing(plan_hub, tmp_path, monkeypatch):
    publish_tests(plan_hub.root, "tester-one", STORY, _text(STORY, 1, "FAIL"))
    result = _invoke(plan_hub, tmp_path, monkeypatch, STORY, "--round", "9")
    assert result.exit_code == 1
    assert "R1" in result.output
    assert not (tmp_path / "docs").exists()


def test_impl_gitignore_ignores_reports():
    text = (
        resources.files("strata_kb.templates.init")
        .joinpath("impl-gitignore.txt")
        .read_text(encoding="utf-8")
    )
    assert "report-R*.md" in text
