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
    entry = make_fed_entry(
        hub / "federation",
        repo_id,
        doc_id,
        title=f"{repo_id} {planingest.TITLE_SUFFIX}",
        tags=["plan", "generated"],
    )
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


@pytest.mark.parametrize(
    "ref", ["../x", "/tmp/x", "..", ".", "a/b", "..\\x", "repo:", "repo:../x", ""]
)
def test_split_ref_refuses_ids_that_are_not_plain_names(ref):
    with pytest.raises(ticketfetch.TicketFetchError, match="not a ticket id"):
        ticketfetch.split_ref(ref)


def test_split_ref_accepts_plain_and_qualified_ids():
    assert ticketfetch.split_ref("M-a-US1") == (None, "M-a-US1")
    assert ticketfetch.split_ref("r-1:M-a-US1") == ("r-1", "M-a-US1")


def _edit_manifest(hub: HubHandle, old: str, new: str) -> None:
    path = hub.root / "federation/ba-one/ba-one-plan/_manifest.yaml"
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_hub_section_id_that_escapes_is_refused(plan_hub):
    _edit_manifest(plan_hub, f"id: {US1}", "id: ../evil")
    with pytest.raises(ticketfetch.TicketFetchError, match="not a ticket id"):
        ticketfetch.find(plan_hub, "../evil")


def test_hub_manifest_file_that_escapes_is_refused(plan_hub):
    _edit_manifest(plan_hub, f"file: {MISSION_ID}", "file: ../../../x")
    with pytest.raises(ticketfetch.TicketFetchError, match="not a plain file name"):
        ticketfetch.find(plan_hub, US1)


def test_find_ignores_a_symlinked_plan_folder(plan_hub, tmp_path):
    from tests.test_planstatus import add_symlinked_plan

    add_symlinked_plan(plan_hub.root / "federation/ba-one", tmp_path / "outside")
    # followed, the copy would make US1 ambiguous between two plan documents
    assert ticketfetch.find(plan_hub, US1)[:2] == ("ba-one", "ba-one-plan")


def test_unreadable_section_file_names_no_hub_path(plan_hub):
    # kb_ticket_fetch returns this message to a remote MCP client.
    _, _, l3 = ticketfetch.find(plan_hub, US1)
    l3.unlink()
    with pytest.raises(ticketfetch.TicketFetchError) as exc:
        ticketfetch.render(plan_hub, US1)
    assert f"/{l3.name}" in str(exc.value)
    assert str(plan_hub.root) not in str(exc.value)


def _bug_hub(fed_hub: Path, tmp_path: Path, run_git) -> tuple[HubHandle, str]:
    """A hub holding a plan whose only ticket is a bug with one PNG."""
    from tests.test_planingest import _PNG, _bug_text, _sha

    ba = tmp_path / "ba-one"
    write_repo(ba, {}, {"bugs/BUG-12.md": _bug_text()})
    folder = ba / "tickets" / "bugs" / "BUG-12"
    folder.mkdir(parents=True)
    (folder / "toast.png").write_bytes(_PNG)
    planingest.run(ba, ba / ".kb", "demo", ba / "missions", ba / "tickets")
    entry = make_fed_entry(
        fed_hub / "federation",
        "ba-one",
        "ba-one-plan",
        title=f"ba-one {planingest.TITLE_SUFFIX}",
        tags=["plan", "generated"],
    )
    shutil.rmtree(entry / "ba-one-plan")
    shutil.copytree(ba / ".kb" / "demo-plan", entry / "ba-one-plan")
    manifest = entry / "ba-one-plan" / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("demo-plan", "ba-one-plan"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "publish bug")
    return HubHandle(root=fed_hub), f"{_sha(_PNG)}.png"


def test_assets_of_lists_the_files_the_fetched_text_references(
    fed_hub, tmp_path, run_git
):
    hub, name = _bug_hub(fed_hub, tmp_path, run_git)
    assert f"](assets/{name})" in ticketfetch.render(hub, "BUG-12")
    files = ticketfetch.assets_of(hub, "BUG-12")
    assert [f.name for f in files] == [name]
    assert files[0].is_file()


def test_assets_of_skips_a_missing_asset_and_a_ticket_without_images(
    fed_hub, tmp_path, run_git, block
):
    hub, name = _bug_hub(fed_hub, tmp_path, run_git)
    files = ticketfetch.assets_of(hub, "BUG-12")
    files[0].unlink()
    assert ticketfetch.assets_of(hub, "BUG-12") == []
    publish_plan(hub.root, "ba-two", tmp_path / "ba-two", block)
    assert ticketfetch.assets_of(hub, "ba-two:" + US1) == []
