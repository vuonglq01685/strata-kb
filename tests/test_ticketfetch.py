"""`kb ticket fetch` engine — a Dev given only a ticket id reads it from the hub."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from strata_kb import gitio, kbcontext, planingest, ticketfetch, ticketlint
from strata_kb.hub import HubHandle
from tests.conftest import make_fed_entry
from tests.test_missionlint import MISSION_ID
from tests.test_planingest import (
    US1,
    context_block,
    mission_text,
    ticket_text,
    write_repo,
)


def publish_plan(hub: Path, repo_id: str, ba_root: Path, block_text: str) -> None:
    """Run plan-ingest on a BA repo (a mission + one ticket) and mirror the
    `<repo_id>-plan` document into the hub the way `kb publish` would."""
    write_repo(
        ba_root,
        {f"{MISSION_ID}.md": mission_text(block_text)},
        {f"{MISSION_ID}/{US1}.md": ticket_text(block_text)},
    )
    planingest.run(
        ba_root, ba_root / ".kb", "demo", ba_root / "missions", ba_root / "tickets"
    )
    doc_id = f"{repo_id}-plan"
    entry = make_fed_entry(hub / "federation", repo_id, doc_id)
    shutil.rmtree(entry / doc_id)
    shutil.copytree(ba_root / ".kb" / "demo-plan", entry / doc_id)
    # the document id is the manifest's own
    manifest = entry / doc_id / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("demo-plan", doc_id),
        encoding="utf-8",
    )


@pytest.fixture
def block(fed_hub: Path) -> str:
    return context_block(fed_hub)


@pytest.fixture
def plan_hub(fed_hub: Path, tmp_path: Path, block: str, run_git) -> HubHandle:
    publish_plan(fed_hub, "ba-one", tmp_path / "ba-one", block)
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "publish ba-one plan")
    return HubHandle(root=fed_hub)


def test_promote_headings_inverse_of_demote():
    md = (
        "> Revision: 1\n\n## Acceptance Criteria\n- [ ] AC1\n\n"
        "### Main flow\n#### Deep\n\n```bash\n# comment\n### not a heading\n```\n\n"
        "## KB context\n"
    )
    assert planingest.promote_headings(planingest.demote_headings(md)) == md


def test_promote_headings_leaves_fences_and_h2_alone():
    md = "## Two\n### Three\n```\n### fenced\n```\n"
    assert planingest.promote_headings(md) == "## Two\n## Three\n```\n### fenced\n```\n"


def test_find_single_holder(plan_hub):
    repo, doc, l3 = ticketfetch.find(plan_hub, US1)
    assert (repo, doc) == ("ba-one", "ba-one-plan")
    assert l3.name == f"{MISSION_ID}.raw.md"
    assert l3.is_file()


def test_find_qualified_ref(plan_hub, tmp_path, block, run_git):
    publish_plan(plan_hub.root, "ba-two", tmp_path / "ba-two", block)
    assert ticketfetch.find(plan_hub, f"ba-two:{US1}")[:2] == ("ba-two", "ba-two-plan")


def test_find_missing_raises_with_publish_hint(plan_hub):
    with pytest.raises(ticketfetch.TicketFetchError) as exc:
        ticketfetch.find(plan_hub, "M-nope-US9")
    assert str(exc.value) == (
        "M-nope-US9 is not on the hub — ask the BA to run kb publish, "
        "or pass the ticket file / paste it"
    )


def test_find_qualifier_naming_another_repo_is_missing(plan_hub):
    with pytest.raises(ticketfetch.TicketFetchError, match="not on the hub"):
        ticketfetch.find(plan_hub, f"other:{US1}")


def test_find_ambiguous_names_holders(plan_hub, tmp_path, block):
    publish_plan(plan_hub.root, "ba-two", tmp_path / "ba-two", block)
    with pytest.raises(ticketfetch.TicketFetchError) as exc:
        ticketfetch.find(plan_hub, US1)
    msg = str(exc.value)
    assert "ba-one" in msg and "ba-two" in msg
    assert f"qualify it as <repo>:{US1}" in msg


def test_render_restores_ticket_shape(plan_hub):
    rendered = ticketfetch.render(plan_hub, US1)
    lines = rendered.split("\n")
    assert lines[0] == "# TAL-1580 — Show restrictive airspace details"
    rev = gitio.head_commit(plan_hub.root)
    assert lines[2] == (
        f"> Fetched from hub: ba-one:ba-one-plan §{US1} @ {rev} "
        "— do not edit; amend in the BA repo."
    )
    assert "## Acceptance Criteria" in lines
    assert "## KB context" in lines
    assert "### Acceptance Criteria" not in rendered
    assert "> Revision: 1" in lines
    assert f"> Parent mission: {MISSION_ID} @ rev 1" in lines
    assert "## Definition of Ready" not in rendered
    assert rendered.endswith("\n")
    assert kbcontext.parse(rendered).refs


def test_render_passes_ticket_lint_structure(plan_hub):
    report = ticketlint.lint(ticketfetch.render(plan_hub, US1), None)
    unexpected = [
        i
        for i in report.issues
        if i.level == "error"
        and i.code != "hub-unreachable"
        and "Definition of Ready" not in i.message
    ]
    assert unexpected == []
