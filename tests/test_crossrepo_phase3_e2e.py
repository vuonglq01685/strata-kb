"""Phase 3 end to end: a mission-time parent (split rows with AC `-`, no child
files) on a hub with two dev repos, `demo` and `web`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models, planingest, planstatus, ticketcheck
from strata_kb.autorun.picker import Task, _ba_tasks
from strata_kb.cli import app
from strata_kb.codeingest import core
from strata_kb.federation import FederationMeta, write_federation_index
from strata_kb.hub import HubHandle
from tests.fixtures_coderepo import build_code_repo
from tests.test_planingest import (
    API,
    US1,
    WEB,
    child_story,
    context_block,
    family,
    write_repo,
)
from tests.test_planstatus import _mirror
from tests.test_planstatus_routing import _dev
from tests.test_ticketcheck import MISSION

runner = CliRunner()
PLANNED = f"| {API} | demo | - | - | - | data |\n| {WEB} | web | - | {API} | - | ui |\n"
SPLIT_DECISION = "**Split decision:** one story per repo, web waits for demo.\n\n"


def _planned_repo(fed_hub: Path, tmp_path: Path, *, write_demo: bool = False) -> Path:
    block = context_block(fed_hub)
    missions, tickets = family(block, split=PLANNED)
    del tickets[f"{API}.md"], tickets[f"{WEB}.md"]
    if write_demo:  # the demo child is drafted and its row filled in
        tickets[f"{API}.md"] = child_story(block, API, "demo", 1)
        tickets[f"{US1}.md"] = tickets[f"{US1}.md"].replace(
            f"| {API} | demo | - |", f"| {API} | demo | AC1, AC2 |"
        )
    tickets[f"{US1}.md"] = tickets[f"{US1}.md"].replace(
        "## Change log\n", f"## Change log\n{SPLIT_DECISION}", 1
    )
    root = tmp_path / "ba-x"
    write_repo(root, missions, tickets)
    return root


def _publish(fed_hub: Path, root: Path) -> HubHandle:
    planingest.run(root, root / ".kb", "demo", root / "missions", root / "tickets")
    _mirror(fed_hub, root, "ba-x")
    for repo in ("demo", "web"):
        _dev(fed_hub, repo)
    return HubHandle(root=fed_hub)


def _lint(fed_hub: Path, root: Path) -> dict:
    result = runner.invoke(
        app,
        ["ticket", "lint", str(root / "tickets" / f"{US1}.md"), "--hub", str(fed_hub)]
        + ["--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _rows(hub: HubHandle) -> dict:
    stories, unparented, _ = planstatus.next_from_hub(hub)
    return {r.us_id: r for r in (*stories, *unparented)}


def test_mission_time_parent_publishes_and_picker_drafts_children(fed_hub, tmp_path):
    root = _planned_repo(fed_hub, tmp_path)
    assert _lint(fed_hub, root)["errors"] == []

    rows = _rows(_publish(fed_hub, root))
    assert (rows[API].status, rows[WEB].status) == ("to-draft", "to-draft")
    assert (rows[US1].status, rows[US1].reasons) == ("in progress", ("0/2 done",))

    result = runner.invoke(
        app,
        ["mission", "next", "--json", "--missions-dir", str(root / "missions")]
        + ["--tickets-dir", str(root / "tickets")],
    )
    assert result.exit_code == 0, result.output
    assert next(_ba_tasks(json.loads(result.output))) == Task("ba-ticket-author", API)


def test_written_child_fills_its_row_and_goes_ready(fed_hub, tmp_path):
    root = _planned_repo(fed_hub, tmp_path, write_demo=True)
    assert _lint(fed_hub, root)["errors"] == []

    rows = _rows(_publish(fed_hub, root))
    assert (rows[API].status, rows[WEB].status) == ("ready", "to-draft")


def _publish_code(fed_hub: Path, kb_dir: Path, repo: str, run_git) -> None:
    """Mirror `<repo>-code` into the hub the way `kb publish` lays it out."""
    entry = fed_hub / "federation" / repo
    shutil.copytree(kb_dir / f"{repo}-code", entry / f"{repo}-code")
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(
            docs=[models.IndexEntry(id=f"{repo}-code", title=repo, tags=["code"])]
        ),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(
            repo_id=repo, source_commit="abc1234", published_at="2026-09-20T00:00:00Z"
        ),
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", f"publish {repo}")


def _ingest(tmp_path: Path, repo: str, run_git) -> tuple[Path, str]:
    root = tmp_path / f"{repo}-src"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    kb_dir = tmp_path / f"{repo}-kb"
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb_dir, doc_id=f"{repo}-code", repo_id=repo
        )
    )
    manifest = models.load_yaml_model(
        kb_dir / f"{repo}-code" / "_manifest.yaml", models.Manifest
    )
    return kb_dir, manifest.revision


def test_two_repo_mission_check_passes(fed_hub, tmp_path, run_git, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    revs = {}
    for repo in ("demo", "web"):
        kb_dir, revs[repo] = _ingest(tmp_path, repo, run_git)
        _publish_code(fed_hub, kb_dir, repo, run_git)
    mission = (
        MISSION
        + f"\n{ticketcheck.SERVICES_HEADING}\n"
        + f"- Grounded on: demo:demo-code @ {revs['demo']}, "
        + f"web:web-code @ {revs['web']}\n\n"
        + "| Order | Service | Depends on | Why this order |\n|---|---|---|---|\n"
        + "| 1 | demo:svc.airspace-service | — | base |\n"
        + "| 2 | web:svc.airspace-service | demo:svc.airspace-service | ui |\n"
    )
    path = tmp_path / "M-demo.md"
    path.write_text(mission, encoding="utf-8")
    result = runner.invoke(
        app,
        ["ticket", "check", str(path), "--hub", str(fed_hub)]
        + ["--kb-dir", str(tmp_path / "empty-kb")]
        + ["--heading", ticketcheck.SERVICES_HEADING],
    )
    assert result.exit_code == 0, result.output
    assert "web-code read from hub federation/web" in result.output
