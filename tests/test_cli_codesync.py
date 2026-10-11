from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.codesync import baseline
from strata_kb.config import KBConfig
from tests.test_codesync_changes import SCAN_SECTIONS, _svc, commit, write_doc

runner = CliRunner()
NO_LEDGER = {
    **SCAN_SECTIONS,
    "svc.payment-service": ("payment-service", _svc("`postgres`")),
}


def _kb(root: Path) -> list[str]:
    return ["--kb-dir", str(root / ".kb")]


def test_scan_md_json_and_exit_codes(code_sync_hub, run_git):
    root, c1 = code_sync_hub

    nothing = runner.invoke(app, ["code-sync", "scan", "--baseline", c1, *_kb(root)])
    assert nothing.exit_code == 0, nothing.output
    assert "nothing to update" in nothing.output

    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    plain = runner.invoke(app, ["code-sync", "scan", "--baseline", c1, *_kb(root)])
    assert plain.exit_code == 2
    assert "arch §4.2: ledger" in plain.output

    md = runner.invoke(app, ["code-sync", "scan", "--md", "--baseline", c1, *_kb(root)])
    assert md.exit_code == 2
    assert "## arch §4.2 Payment flow" in md.output
    assert "<!-- kb-code-sync digest:" in md.output

    data = runner.invoke(
        app, ["code-sync", "scan", "--json", "--baseline", c1, *_kb(root)]
    )
    assert data.exit_code == 2
    assert json.loads(data.output)["findings"][0]["term"] == "ledger"

    bad = runner.invoke(
        app, ["code-sync", "scan", "--baseline", "deadbeefcafe1234", *_kb(root)]
    )
    assert bad.exit_code == 1
    assert "does not exist" in bad.output


def test_scan_without_baseline_file_exits_0_with_note(code_sync_hub):
    root, _ = code_sync_hub

    result = runner.invoke(app, ["code-sync", "scan", *_kb(root)])

    assert result.exit_code == 0, result.output
    assert "no baseline — run kb code-sync baseline" in result.output


@pytest.mark.parametrize("value", ["HEAD~1", "--output=x", "xyz"])
def test_scan_rejects_non_sha_baseline(code_sync_hub, value):
    root, _ = code_sync_hub

    result = runner.invoke(app, ["code-sync", "scan", "--baseline", value, *_kb(root)])

    assert result.exit_code == 1
    assert "not a commit sha" in result.output


def test_scan_remote_without_origin_head_exits_1(code_sync_hub, run_git, tmp_path):
    root, _ = code_sync_hub
    run_git(root, "remote", "add", "origin", str(tmp_path / "nowhere.git"))

    result = runner.invoke(app, ["code-sync", "scan", *_kb(root)])

    assert result.exit_code == 1
    assert "origin/HEAD is not set" in result.output


def test_baseline_writes_scan_sha_by_default(code_sync_hub):
    root, c1 = code_sync_hub

    result = runner.invoke(app, ["code-sync", "baseline", *_kb(root)])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == c1
    assert (root / baseline.BASELINE_FILE).read_text() == f"baseline: {c1}\n"


def test_baseline_at_sha(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)

    result = runner.invoke(app, ["code-sync", "baseline", "--at", c1[:10], *_kb(root)])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == c1
    assert baseline.parse((root / baseline.BASELINE_FILE).read_text()) == c1


def test_baseline_rejects_bad_or_unknown_sha(code_sync_hub):
    root, _ = code_sync_hub
    for value in ("HEAD", "deadbeefcafe1234"):
        result = runner.invoke(
            app, ["code-sync", "baseline", "--at", value, *_kb(root)]
        )
        assert result.exit_code == 1
    assert not (root / baseline.BASELINE_FILE).exists()


@pytest.mark.parametrize("command", ["scan", "baseline"])
def test_non_hub_kind_exits_1(code_sync_hub, command):
    root, _ = code_sync_hub
    models.save_yaml_model(root / ".kb" / "config.yaml", KBConfig(kind="child"))

    result = runner.invoke(app, ["code-sync", command, *_kb(root)])

    assert result.exit_code == 1
    assert "kind: hub" in result.output
    assert not (root / baseline.BASELINE_FILE).exists()


def test_half_published_hub_doc_exits_1(code_sync_hub, run_git):
    root, c1 = code_sync_hub
    (root / "federation" / "kb-hub" / "arch" / "ch1.raw.md").unlink()
    commit(root, run_git)

    result = runner.invoke(app, ["code-sync", "scan", "--baseline", c1, *_kb(root)])

    assert result.exit_code == 1
    assert "ch1.raw.md is missing" in result.output
