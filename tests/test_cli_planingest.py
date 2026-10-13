"""`kb plan-ingest` CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.cli import app
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import context_block, mission_text, write_repo

runner = CliRunner()


@pytest.fixture
def block(fed_hub: Path) -> str:
    return context_block(fed_hub)


def _invoke(root: Path, *extra: str):
    return runner.invoke(
        app,
        [
            "plan-ingest",
            "--repo-root",
            str(root),
            "--kb-dir",
            str(root / ".kb"),
            "--missions-dir",
            str(root / "missions"),
            "--tickets-dir",
            str(root / "tickets"),
            *extra,
        ],
    )


def _config(root: Path, repo_id: str) -> None:
    (root / ".kb").mkdir(exist_ok=True)
    (root / ".kb" / "config.yaml").write_text(
        f'kind: ba\nhub: ""\nrepo_id: "{repo_id}"\nintake: ""\n', encoding="utf-8"
    )


def test_json_output_has_doc_id_published_and_skipped(tmp_path: Path, block: str):
    _config(tmp_path, "acme")
    write_repo(
        tmp_path,
        {
            f"{MISSION_ID}.md": mission_text(block),
            "M-held.md": mission_text(block, skip="## Scope").replace(
                MISSION_ID, "M-held"
            ),
        },
        {},
    )
    result = _invoke(tmp_path, "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert set(payload) == {"doc_id", "published", "skipped"}
    assert payload["doc_id"] == "acme-plan"
    assert payload["published"] == [MISSION_ID]
    assert payload["skipped"][0][0] == "missions/M-held.md"


def test_text_report_prints_skipped_lines_and_step_summary(
    tmp_path: Path, block: str, monkeypatch: pytest.MonkeyPatch
):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block, skip="## Scope")}, {})
    result = _invoke(tmp_path)
    assert result.exit_code == 0, result.output
    assert f"skipped: missions/{MISSION_ID}.md — " in result.output
    assert f"skipped: missions/{MISSION_ID}.md" in summary.read_text(encoding="utf-8")


def test_bad_missions_dir_exits_1(tmp_path: Path):
    (tmp_path / "tickets").mkdir()
    result = _invoke(tmp_path)
    assert result.exit_code == 1
    assert "--missions-dir" in result.output


def test_default_repo_id_comes_from_config(tmp_path: Path, block: str):
    _config(tmp_path, "dashboard")
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    assert _invoke(tmp_path).exit_code == 0
    assert (tmp_path / ".kb/dashboard-plan/_manifest.yaml").is_file()


def test_repo_id_flag_overrides_config(tmp_path: Path, block: str):
    _config(tmp_path, "dashboard")
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    assert _invoke(tmp_path, "--repo-id", "other").exit_code == 0
    assert (tmp_path / ".kb/other-plan/_manifest.yaml").is_file()


def test_invalid_repo_id_exits_1(tmp_path: Path):
    write_repo(tmp_path, {}, {})
    result = _invoke(tmp_path, "--repo-id", "bad id")
    assert result.exit_code == 1
