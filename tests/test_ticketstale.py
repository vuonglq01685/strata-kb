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


# --- architecture drift (spec B2) -------------------------------------------


def _publish(hub: Path, run_git, revision: str, **bodies: str) -> str:
    """Rewrite federation/demo/demo-code with one section per `svc_<x>` kwarg
    (`svc_a="..."` -> section `svc.a`), set its manifest `revision:` and
    commit to the hub. Returns the full hub commit."""
    from strata_kb import models
    from tests.conftest import make_fed_entry

    fed = hub / "federation"
    if (fed / "demo").exists():
        shutil.rmtree(fed / "demo")
    entry = make_fed_entry(fed, "demo", "demo-code", sec_id="svc.a")
    sections = {k.replace("_", ".", 1): v for k, v in bodies.items()}
    manifest = models.load_yaml_model(
        entry / "demo-code" / "_manifest.yaml", models.Manifest
    )
    manifest.revision = revision
    manifest.title = repr(sorted(bodies.items()))  # every publish touches the manifest
    manifest.sections = [
        models.SectionEntry(
            id=sid, title=sid, summary="s", status="summarized", file="ch1"
        )
        for sid in sections
    ]
    models.save_yaml_model(entry / "demo-code" / "_manifest.yaml", manifest)
    (entry / "demo-code" / "ch1.md").write_text(
        "\n".join(f"## {sid} {sid}\n\n{body}\n" for sid, body in sections.items()),
        encoding="utf-8",
    )
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", f"publish {revision}")
    return run_git(hub, "rev-parse", "HEAD")


def _ticket(root: Path, rev: str, body: str, name: str = "T-9.md") -> Path:
    path = root / "tickets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# T-9\n\n## Technical grounding\n- Grounded on: demo:demo-code @ {rev}\n"
        f"{body}\n\n## Other\nsvc.zzz mentioned elsewhere.\n",
        encoding="utf-8",
    )
    return path


def _arch(root: Path, fed_hub: Path):
    return ticketstale.scan([root / "tickets"], HubHandle(root=fed_hub))


def test_architecture_unchanged_section_no_finding(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1", svc_b="B1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A1", svc_b="B2")  # only svc.b moved
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    assert _arch(tmp_path, fed_hub) == []


def test_architecture_changed_cited_section_is_stale(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1", svc_b="B1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A1", svc_b="B2")
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`, `svc.b`")
    findings = _arch(tmp_path, fed_hub)
    [f] = findings
    [ref] = f.refs
    assert (ref.kind, ref.status) == ("architecture", "stale")
    assert "svc.b" in ref.citation
    assert ticketstale.exit_code(findings) == 2


def test_architecture_removed_section_is_broken(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1", svc_b="B1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A1")  # svc.b gone
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.b`")
    findings = _arch(tmp_path, fed_hub)
    assert [(r.kind, r.status) for f in findings for r in f.refs] == [
        ("architecture", "broken")
    ]
    assert ticketstale.exit_code(findings) == 1


def test_architecture_new_marker_row_skipped(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1", svc_b="B1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A1")
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`\n- New: `svc.b` [NEW: D1]")
    assert _arch(tmp_path, fed_hub) == []


def test_architecture_baseline_newest_commit_wins(tmp_path, fed_hub, run_git):
    # The same revision published twice: the newest hub commit is the baseline,
    # so a section that only changed between the two is not drift.
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A2")
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    assert _arch(tmp_path, fed_hub) == []


def test_architecture_baseline_not_on_hub(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    _ticket(tmp_path, "ccccccc", "- Services: `svc.a`, `svc.b`")
    [f] = _arch(tmp_path, fed_hub)
    [ref] = f.refs
    assert (ref.status, ref.reason, ref.kind) == (
        "stale",
        "baseline not on hub",
        "architecture",
    )
    assert ref.citation == "demo-code @ ccccccc"


def test_architecture_full_manifest_revision_matches_short_pin(
    tmp_path, fed_hub, run_git
):
    _publish(fed_hub, run_git, "aaaaaaa1234567", svc_a="A1")
    _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    assert _arch(tmp_path, fed_hub) == []


def test_architecture_runs_without_a_kb_context_block(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A2")
    path = _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    assert "kb-context" not in path.read_text(encoding="utf-8")
    [f] = _arch(tmp_path, fed_hub)
    assert [r.kind for r in f.refs] == ["architecture"]


def test_architecture_unqualified_entry_uses_unique_holder(tmp_path, fed_hub, run_git):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A2")
    path = _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    path.write_text(
        path.read_text(encoding="utf-8").replace("demo:demo-code", "demo-code"),
        encoding="utf-8",
    )
    [f] = _arch(tmp_path, fed_hub)
    assert [(r.kind, r.status) for r in f.refs] == [("architecture", "stale")]


def test_architecture_unqualified_entry_without_unique_holder_is_a_finding(
    tmp_path, fed_hub, run_git
):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    path = _ticket(tmp_path, "aaaaaaa", "- Services: `svc.a`")
    path.write_text(
        path.read_text(encoding="utf-8").replace("demo:demo-code", "nowhere-code"),
        encoding="utf-8",
    )
    [f] = _arch(tmp_path, fed_hub)
    assert [(r.kind, r.status) for r in f.refs] == [("architecture", "broken")]


def test_architecture_mission_reads_services_section_svc_only(
    tmp_path, fed_hub, run_git
):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    _publish(fed_hub, run_git, "bbbbbbb", svc_a="A2")
    mission = tmp_path / "missions" / "M-x.md"
    mission.parent.mkdir()
    mission.write_text(
        "# M\n\n## Services & order\n- Grounded on: demo:demo-code @ aaaaaaa\n"
        "- `db.gone` and `svc.a`\n",
        encoding="utf-8",
    )
    findings = ticketstale.scan([mission], HubHandle(root=fed_hub))
    [ref] = findings[0].refs
    assert "svc.a" in ref.citation and ref.status == "stale"


def test_architecture_no_grounded_line_or_no_ids_yields_nothing(
    tmp_path, fed_hub, run_git
):
    _publish(fed_hub, run_git, "aaaaaaa", svc_a="A1")
    hub = HubHandle(root=fed_hub)
    path = tmp_path / "T.md"
    no_line = "# T\n\n## Technical grounding\n- Services: `svc.a`\n"
    assert ticketstale.architecture_refs(path, no_line, hub) == []
    no_ids = "# T\n\n## Technical grounding\n- Grounded on: demo:demo-code @ aaaaaaa\n"
    assert ticketstale.architecture_refs(path, no_ids, hub) == []


def test_render_markdown_has_kind_column():
    findings = [
        ticketstale.StaleFile(
            "tickets/T.md",
            [
                ticketstale.StaleRef("a §1", "stale", "x"),
                ticketstale.StaleRef(
                    "demo-code §svc.a", "stale", "y", kind="architecture"
                ),
            ],
        )
    ]
    body = ticketstale.render_markdown(findings)
    assert "| File | Kind | Citation | Status | Reason |" in body
    assert "| `tickets/T.md` | kb-context | a §1 | stale | x |" in body
    assert "| `tickets/T.md` | architecture | demo-code §svc.a | stale | y |" in body
    assert ticketstale.to_json(findings)[0]["refs"][1]["kind"] == "architecture"
