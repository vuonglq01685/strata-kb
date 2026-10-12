from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import ghio, models
from strata_kb.cli import app
from strata_kb.codesync import baseline, scan
from strata_kb.config import KBConfig
from tests.test_codesync_changes import SCAN_SECTIONS, _db, _svc, commit, write_doc

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


# --- kb code-sync issue ----------------------------------------------------


def _job_issue(root: Path, run_git, number: int = 7) -> tuple[dict, str]:
    """c1 is recorded, the code docs moved after it and the job wrote the
    issue from that state; `(issue, c1)`."""
    c1 = run_git(root, "rev-parse", "HEAD")
    baseline.write(root, c1)
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    body = scan.render_markdown(scan.run_scan(root))
    issue = {
        "number": number,
        "url": f"https://github.com/o/hub/issues/{number}",
        "createdAt": "2026-10-11T08:00:00Z",
        "body": body,
    }
    return issue, c1


def _gh_issues(monkeypatch, issues) -> list:
    seen: list = []

    def fake(root, label):
        seen.append(label)
        return issues

    monkeypatch.setattr(ghio, "list_open_issues", fake)
    return seen


def test_issue_current_exit_0_text_and_json(code_sync_hub, run_git, monkeypatch):
    root, _ = code_sync_hub
    issue, c1 = _job_issue(root, run_git)
    foreign = {**issue, "number": 9, "body": "hello"}
    seen = _gh_issues(monkeypatch, [foreign, issue])

    text = runner.invoke(app, ["code-sync", "issue", *_kb(root)])
    data = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert seen == ["kb-code-sync", "kb-code-sync"]
    assert text.exit_code == 0, text.output
    assert text.output.splitlines()[0].startswith("#7 [current] ")
    assert text.output.splitlines()[1] == "#9 [foreign] no work-order marker"
    assert data.exit_code == 0, data.output
    out = json.loads(data.output)
    assert (out["usable"], out["baseline_sha"]) == (7, c1)
    assert out["issue_baseline_sha"] == c1
    assert [(i["number"], i["kind"]) for i in out["issues"]] == [
        (7, "current"),
        (9, "foreign"),
    ]


def test_issue_stale_is_usable(code_sync_hub, run_git, monkeypatch):
    root, _ = code_sync_hub
    issue, c1 = _job_issue(root, run_git)
    write_doc(
        root,
        "acme",
        "code",
        {**NO_LEDGER, "db.payments": ("payments", _db("amount", "refund_id"))},
    )
    commit(root, run_git)
    _gh_issues(monkeypatch, [issue])

    result = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert (out["usable"], out["baseline_sha"]) == (7, c1)
    assert out["issues"][0]["kind"] == "stale"


def test_issue_none_usable_exits_2(code_sync_hub, monkeypatch):
    root, _ = code_sync_hub
    foreign = {"number": 3, "url": "u", "createdAt": "t", "body": "x"}
    _gh_issues(monkeypatch, [foreign])

    text = runner.invoke(app, ["code-sync", "issue", *_kb(root)])
    data = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert text.exit_code == 2
    assert "#3 [foreign]" in text.output
    assert data.exit_code == 2
    out = json.loads(data.output)
    assert (out["usable"], out["baseline_sha"], out["issue_baseline_sha"]) == (
        None,
        None,
        None,
    )
    assert out["issues"][0]["number"] == 3


def test_issue_no_open_issues_exits_2(code_sync_hub, monkeypatch):
    root, _ = code_sync_hub
    _gh_issues(monkeypatch, [])

    result = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert result.exit_code == 2
    assert json.loads(result.output) == {
        "usable": None,
        "baseline_sha": None,
        "issue_baseline_sha": None,
        "issues": [],
    }


def test_issue_rerun_after_baseline_moved_scans_from_the_recorded_baseline(
    code_sync_hub, run_git, monkeypatch
):
    root, _ = code_sync_hub
    issue, c1 = _job_issue(root, run_git)
    moved = scan.run_scan(root).scan_sha
    baseline.write(root, moved)
    commit(root, run_git)
    _gh_issues(monkeypatch, [issue])

    result = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["issues"][0]["kind"] == "stale"
    assert (out["usable"], out["baseline_sha"], out["issue_baseline_sha"]) == (
        7,
        moved,
        c1,
    )
    scanned = runner.invoke(
        app, ["code-sync", "scan", "--json", "--baseline", moved, *_kb(root)]
    )
    assert json.loads(scanned.output)["findings"] == []


def test_issue_without_recorded_baseline_is_usable_with_null_baseline(
    code_sync_hub, run_git, monkeypatch
):
    root, _ = code_sync_hub
    issue, _ = _job_issue(root, run_git)
    (root / baseline.BASELINE_FILE).unlink()
    commit(root, run_git)
    _gh_issues(monkeypatch, [issue])

    result = runner.invoke(app, ["code-sync", "issue", "--json", *_kb(root)])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert (out["usable"], out["baseline_sha"]) == (7, None)
    assert "no recorded baseline" in out["issues"][0]["reason"]


def test_issue_gh_failure_exits_1(code_sync_hub, monkeypatch):
    root, _ = code_sync_hub

    def boom(root, label):
        raise ghio.GHError("gh issue list failed: bad token")

    monkeypatch.setattr(ghio, "list_open_issues", boom)

    result = runner.invoke(app, ["code-sync", "issue", *_kb(root)])

    assert result.exit_code == 1
    assert "bad token" in result.output


def test_issue_non_hub_exits_1(code_sync_hub, monkeypatch):
    root, _ = code_sync_hub
    models.save_yaml_model(root / ".kb" / "config.yaml", KBConfig(kind="child"))
    seen = _gh_issues(monkeypatch, [])

    result = runner.invoke(app, ["code-sync", "issue", *_kb(root)])

    assert result.exit_code == 1
    assert "kind: hub" in result.output
    assert seen == []
