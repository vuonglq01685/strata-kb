"""`kb ticket stale` (1.16.0, review H14): sweep every ticket and mission
for citations the hub has moved since they were pinned."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import kbcontext, ticketstale
from strata_kb.cli import app
from strata_kb.hub import HubHandle
from tests.conftest import make_stale

runner = CliRunner()
REFS = ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"]


@pytest.fixture
def repo(tmp_path: Path, fed_hub: Path) -> Path:
    """A BA repo with two pinned tickets, a mission, a draft with no block and
    a ticket whose block does not parse."""
    root = tmp_path / "ba-repo"
    (root / "tickets" / "sprint-1").mkdir(parents=True)
    (root / "missions").mkdir()
    block, _ = kbcontext.build_context_block(HubHandle(root=fed_hub), REFS)
    for rel in ("tickets/sprint-1/T-1.md", "tickets/T-2.md", "missions/M-a.md"):
        (root / rel).write_text(f"# {rel}\n\n{block}\n", encoding="utf-8")
    (root / "tickets" / "draft.md").write_text("# draft, no block\n", encoding="utf-8")
    (root / "tickets" / "bad.md").write_text(
        "# bad\n\nkb-context:\n  refs: [not a ref\n", encoding="utf-8"
    )
    return root


def _scan(repo: Path, fed_hub: Path):
    return ticketstale.scan(
        [repo / "tickets", repo / "missions"], HubHandle(root=fed_hub)
    )


def test_current_citations_report_nothing(repo, fed_hub):
    findings = _scan(repo, fed_hub)
    assert findings == []
    assert ticketstale.exit_code(findings) == 0


def test_an_amended_section_marks_every_citing_file_stale(repo, fed_hub):
    make_stale(fed_hub)
    findings = _scan(repo, fed_hub)
    assert sorted(Path(f.path).name for f in findings) == ["M-a.md", "T-1.md", "T-2.md"]
    for f in findings:
        assert [(r.citation.split(" (")[0], r.status) for r in f.refs] == [
            ("icao-kb:icao-annex-2 §1.1", "stale")
        ]
    assert ticketstale.exit_code(findings) == 2


def test_a_removed_document_is_broken(repo, fed_hub):
    shutil.rmtree(fed_hub / "federation" / "arinc-kb" / "arinc-424")
    findings = _scan(repo, fed_hub)
    assert {r.status for f in findings for r in f.refs} == {"broken"}
    assert ticketstale.exit_code(findings) == 1


def test_markdown_lists_each_citation_once(repo, fed_hub):
    make_stale(fed_hub)
    body = ticketstale.render_markdown(_scan(repo, fed_hub))
    assert body.startswith("3 citation(s) in 3 file(s)")
    assert body.count("| stale |") == 3
    assert "kb context new" in body
    assert ticketstale.render_markdown([]).startswith("Every ticket")


def test_cli_defaults_to_tickets_and_missions(repo, fed_hub, monkeypatch):
    monkeypatch.chdir(repo)
    hub = ["--hub", str(fed_hub)]
    assert runner.invoke(app, ["ticket", "stale", *hub]).exit_code == 0
    make_stale(fed_hub)
    result = runner.invoke(app, ["ticket", "stale", "--json", *hub])
    assert result.exit_code == 2
    data = json.loads(result.output)
    assert sorted(Path(d["path"]).name for d in data) == ["M-a.md", "T-1.md", "T-2.md"]
    result = runner.invoke(app, ["ticket", "stale", "--md", "tickets/T-2.md", *hub])
    assert result.exit_code == 2
    assert result.output.startswith("1 citation(s) in 1 file(s)")


def test_kb_doctor_workflow_is_scaffolded_for_ba_and_dev_only():
    import yaml

    from strata_kb.initcmd import expected_files, read_template

    rel = ".github/workflows/kb-doctor.yml"
    assert rel in expected_files("ba") and rel in expected_files("dev")
    assert rel not in expected_files("hub") and rel not in expected_files("child")
    workflow = yaml.safe_load(read_template("kb-doctor.yml"))
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    assert "schedule" in workflow[True]  # YAML 1.1 reads the `on:` key as True
    steps = "\n".join(
        str(step.get("run", ""))
        for step in workflow["jobs"]["stale-citations"]["steps"]
    )
    assert "kb ticket stale --md" in steps
    assert "gh issue close" in steps and "gh issue create" in steps
