"""`kb ticket check` — the CLI wrapper over `ticketcheck.check`, both
document sources: local --kb-dir and the hub federation mirror."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.federation import FederationMeta, write_federation_index
from tests.test_ticketcheck import MISSION, grounding, mission_with_services, ticket

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_stray_hub_env(monkeypatch):
    """`ticket check` now resolves the hub on every run (hub-first, Task 7):
    without this, a developer's real `STRATA_KB_HUB` would leak into every
    test in this module and make "no hub" / "unreachable hub" cases contact
    an actual hub instead of exercising the local fallback."""
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)


def _publish_to_hub(fed_hub: Path, kb_dir: Path, repo_id: str, run_git) -> None:
    """Mirror `demo-code` into `fed_hub/federation/<repo_id>/` the way
    `kb publish` lays it out (full .kb mirror + _meta.yaml + index.yaml)."""
    entry = fed_hub / "federation" / repo_id
    shutil.copytree(kb_dir / "demo-code", entry / "demo-code")
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-code", title="demo — code knowledge", tags=["code"])]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id=repo_id, source_commit="abc1234", published_at="2026-09-20T00:00:00+00:00"),
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", f"publish {repo_id}")


def test_local_kb_dir_golden_exits_0(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("Grounding: PASS")
    assert "[note] demo-code read from" in result.output
    assert "(local fallback" in result.output


def test_bad_id_exits_1_and_names_it(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, Service="svc.nope")), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "[error] unknown id 'svc.nope'" in result.output
    assert "(line 8)" in result.output
    assert result.output.rstrip().endswith("Grounding: FAIL")


def test_json_output_shape(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, **{"Open decisions": ["retry policy?"]})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["pass"] is False
    assert any("open decision: retry policy?" in e for e in data["errors"])
    assert set(data) == {"pass", "errors", "warnings", "notes"}


def test_reads_stdin(code_doc):
    kb_dir, rev = code_doc
    result = runner.invoke(app, ["ticket", "check", "-", "--kb-dir", str(kb_dir)], input=ticket(grounding(rev)))
    assert result.exit_code == 0, result.output


def test_non_utf8_file_is_a_red_line_not_a_traceback(code_doc, tmp_path):
    kb_dir, _ = code_doc
    path = tmp_path / "t.md"
    path.write_bytes(b"\xff\xfe# bad")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_hub_branch_resolves_the_document_from_the_federation(code_doc, fed_hub, run_git, tmp_path):
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "[note] demo-code read from hub federation/demo" in result.output


def test_hub_ambiguous_holders_need_a_repo_qualifier(code_doc, fed_hub, run_git, tmp_path):
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    _publish_to_hub(fed_hub, kb_dir, "demo-fork", run_git)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, **{"Grounded on": "demo-code @ {rev}"})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 1
    assert "several repos" in result.output and "demo, demo-fork" in result.output
    path.write_text(ticket(grounding(rev, **{"Grounded on": "demo-fork:demo-code @ {rev}"})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "read from hub federation/demo-fork" in result.output


def test_hub_not_needed_when_the_document_is_local(code_doc, tmp_path):
    # No --hub, no config: the local branch must not call _hub_or_exit.
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output


def test_docs_name_the_check_command():
    from importlib import resources
    from pathlib import Path as _P

    readme = (_P(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "`kb ticket check <file\\|-> [--kb-dir <dir>] [--hub <url>] [--json] [--missions-dir <dir>] [--heading <h2>]`" in readme
    quick = resources.files("strata_kb").joinpath("templates/init/QUICKSTART-ba.md").read_text(encoding="utf-8")
    assert "- `kb ticket check <file> [--missions-dir <dir>] [--heading <h2>] [--hub <url>]`" in quick
    for name in ("claude-skill-sa-ticket-ground.md", "copilot-sa-ticket-ground.prompt.md", "cursor-sa-ticket-ground.md"):
        text = resources.files("strata_kb").joinpath(f"templates/init/{name}").read_text(encoding="utf-8")
        assert "has no `ticket check` command yet" not in text, name
    changelog = (_P(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "follows in a\n  separate PR" not in changelog
    assert "`kb ticket check <file>`" in changelog


def _layout(tmp_path: Path, rev: str, section_kwargs: dict, *, parent: str | None = "M-demo") -> Path:
    """tickets/t.md next to missions/M-demo.md — the layout kb init scaffolds."""
    (tmp_path / "tickets").mkdir()
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "tickets" / "t.md"
    path.write_text(ticket(grounding(rev, **section_kwargs), parent=parent), encoding="utf-8")
    return path


def test_sibling_missions_dir_is_the_default(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = _layout(tmp_path, rev, {
        "Service": "svc.billing [NEW: D1]",
        "Volumes": None, "Healthchecks": None, "Devices": None,
    })
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
    assert "[note] new: svc.billing — D1 (DECIDED, owner tech-lead)" in result.output


def test_no_sibling_default_outside_a_tickets_directory(code_doc, tmp_path):
    kb_dir, rev = code_doc
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, Service="svc.billing [NEW: D1]"), parent="M-demo"), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "parent mission 'M-demo' not found" in result.output


def test_explicit_missions_dir(code_doc, tmp_path):
    kb_dir, rev = code_doc
    elsewhere = tmp_path / "plans"
    elsewhere.mkdir()
    (elsewhere / "M-demo.md").write_text(MISSION, encoding="utf-8")
    path = tmp_path / "t.md"
    path.write_text(
        ticket(grounding(rev, Service="svc.billing [NEW: D1]", Volumes=None, Healthchecks=None, Devices=None), parent="M-demo"),
        encoding="utf-8",
    )
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--missions-dir", str(elsewhere)]
    )
    assert result.exit_code == 0, result.output


def test_bad_explicit_missions_dir_is_a_red_line(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--missions-dir", str(tmp_path / "nope")]
    )
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output


def test_open_decision_reference_exits_1(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = _layout(tmp_path, rev, {"Tables": "db.invoice [NEW: D2]"})
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "[error] decision D2 is OPEN (owner: Alice)" in result.output


def test_heading_services_and_order(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "M-demo.md"
    path.write_text(mission_with_services(rev, "svc.billing [NEW: D1]"), encoding="utf-8")
    result = runner.invoke(
        app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--heading", "## Services & order"]
    )
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("Grounding: PASS")


def test_hub_copy_wins_over_a_local_copy(code_doc, fed_hub, run_git, tmp_path):
    # Spec 2026-09-25 §4.1: a dev repo's local -code is regenerated from its
    # branch, so its revision is never the one the SA grounded on.
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    manifest_path = kb_dir / "demo-code" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.revision = "0000000"
    models.save_yaml_model(manifest_path, manifest)
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir),
                                 "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "[note] demo-code read from hub federation/demo" in result.output


def test_local_copy_is_the_fallback_when_no_hub_is_reachable(code_doc, tmp_path):
    # A --hub path that resolves to nothing: no local path with a `.kb/`,
    # no cache, no clone target -- genuinely unreachable, not just
    # "unconfigured" (that's the module-level `_no_stray_hub_env` case).
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir),
                                 "--hub", str(tmp_path / "nope")])
    assert result.exit_code == 0, result.output
    assert "(local fallback — could not reach hub" in result.output


def test_local_copy_is_the_fallback_when_the_hub_lacks_the_doc(code_doc, fed_hub, tmp_path):
    # fed_hub is a reachable hub, but it never published demo-code.
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir),
                                 "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "(local fallback — not on the hub)" in result.output
