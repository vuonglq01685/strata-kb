"""`kb plan-ingest` — the `<repo_id>-plan` document built from missions/ and tickets/."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from strata_kb import build, kbcontext, models, planingest
from strata_kb.hub import HubHandle
from strata_kb.mdutils import (
    extract_tables,
    normalize_table,
    section_map,
    slice_section,
)
from tests.test_missionlint import MISSION_ID, REFS, _build_mission
from tests.test_ticketlint import _build_ticket

US1 = f"{MISSION_ID}-US1"
TICKED = "- [x] a\n- [x] b\n- [x] c"
PARENT = f"> Parent mission: {MISSION_ID} @ rev 1"
CHANGE_LOG = (
    "| Rev | Date | Trigger | What changed | Affected | Review |\n"
    "|---|---|---|---|---|---|\n"
    f"| 2 | 2026-10-11 | scope | split US1 | {US1} | B4 D4 (agent) |"
)


def context_block(fed_hub: Path) -> str:
    text, warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return text


@pytest.fixture
def block(fed_hub: Path) -> str:
    return context_block(fed_hub)


def mission_text(block: str, *, ticked: bool = True, **kw) -> str:
    if ticked:
        kw["overrides"] = {"## Definition of Ready": TICKED, **kw.get("overrides", {})}
    return _build_mission(block, **kw)


def ticket_text(block: str, *, ticked: bool = True, parent: str | None = PARENT):
    text = _build_ticket(
        block, overrides={"## Definition of Ready": TICKED} if ticked else None
    )
    if parent:
        text = text.replace("> Revision: 1\n", f"> Revision: 1\n{parent}\n", 1)
    return text


def write_repo(root: Path, missions: dict[str, str], tickets: dict[str, str]) -> None:
    for folder, files in (("missions", missions), ("tickets", tickets)):
        (root / folder).mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            path = root / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))


def run_plan(root: Path) -> planingest.PlanIngestReport:
    return planingest.run(
        root, root / ".kb", "demo", root / "missions", root / "tickets"
    )


def doc_file(root: Path, name: str) -> str:
    return (root / ".kb" / "demo-plan" / name).read_text(encoding="utf-8")


def test_publishes_lint_clean_mission_with_ticked_dor(tmp_path: Path, block: str):
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    report = run_plan(tmp_path)
    assert report.published == [MISSION_ID]
    assert report.skipped == []
    assert (tmp_path / ".kb/demo-plan" / f"{MISSION_ID}.md").is_file()
    l3 = doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    assert f"## {MISSION_ID} Filter and display controlled airspace" in l3


def test_publishes_mission_with_unticked_dor(tmp_path: Path, block: str):
    """A mission ships as soon as it lints: its DoR is not a publish gate."""
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block, ticked=False)}, {})
    report = run_plan(tmp_path)
    assert report.published == [MISSION_ID]
    assert report.skipped == []


def test_skips_mission_failing_offline_lint(tmp_path: Path, block: str):
    text = mission_text(block, skip="## Scope")
    write_repo(tmp_path, {f"{MISSION_ID}.md": text}, {})
    (reason,) = [r for _, r in run_plan(tmp_path).skipped]
    assert reason.startswith("lint error:")


def test_ticket_goes_in_parent_mission_group(tmp_path: Path, block: str):
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block)},
        {f"{MISSION_ID}/{US1}.md": ticket_text(block)},
    )
    report = run_plan(tmp_path)
    assert report.published == [MISSION_ID, US1]
    l3 = doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    assert f"## {US1} TAL-1580 — Show restrictive airspace details" in l3
    assert not (tmp_path / ".kb/demo-plan/tickets.md").exists()


def test_unparented_ticket_goes_in_tickets_group(tmp_path: Path, block: str):
    write_repo(tmp_path, {}, {"TAL-1580.md": ticket_text(block, parent=None)})
    report = run_plan(tmp_path)
    assert report.published == ["TAL-1580"]
    assert "## TAL-1580 " in doc_file(tmp_path, "tickets.raw.md")


def test_ticket_of_skipped_mission_goes_in_tickets_group(tmp_path: Path, block: str):
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block, skip="## Scope")},
        {f"{US1}.md": ticket_text(block)},
    )
    report = run_plan(tmp_path)
    assert report.published == [US1]
    assert f"## {US1} " in doc_file(tmp_path, "tickets.raw.md")
    assert not (tmp_path / ".kb/demo-plan" / f"{MISSION_ID}.md").exists()


def test_demoted_ticket_is_skipped(tmp_path: Path, block: str):
    mission = mission_text(block, extra={"## Change log": CHANGE_LOG}).replace(
        "> Revision: 1", "> Revision: 2", 1
    )
    write_repo(
        tmp_path, {f"{MISSION_ID}.md": mission}, {f"{US1}.md": ticket_text(block)}
    )
    report = run_plan(tmp_path)
    assert report.published == [MISSION_ID]
    ((file, reason),) = report.skipped
    assert file == f"tickets/{US1}.md"
    assert reason.startswith("parent mission rev")


def test_ticket_with_unticked_dor_is_skipped(tmp_path: Path, block: str):
    write_repo(tmp_path, {}, {"T-1.md": ticket_text(block, ticked=False, parent=None)})
    assert run_plan(tmp_path).published == []


def test_l3_drops_review_record_and_dor_keeps_open_questions(
    tmp_path: Path, block: str
):
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    run_plan(tmp_path)
    l3 = doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    assert "Review record" not in l3
    assert "Definition of Ready" not in l3
    assert "### Open questions" in l3
    assert "Confirm map tile provider quota" in l3
    assert "### Summary" in l3
    assert "\n# Filter" not in l3


def test_demote_headings_skips_fences():
    src = "## a\n```\n## x\n```\n### b\n~~~md\n# y\n~~~\n"
    assert planingest.demote_headings(src) == (
        "### a\n```\n## x\n```\n#### b\n~~~md\n# y\n~~~\n"
    )


FENCE_REASON = "fenced line starting with '## ' would split the section"


def test_item_with_fenced_h2_line_is_skipped(tmp_path: Path, block: str):
    bad = "Scope.\n\n```md\n## inside\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |"
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block, overrides={"## Scope": bad})},
        {
            f"{US1}.md": ticket_text(block).replace(
                "Main flow", "Main flow\n```\n## x\n```"
            )
        },
    )
    report = run_plan(tmp_path)
    assert report.published == []
    assert [f for f, _ in report.skipped] == [
        f"missions/{MISSION_ID}.md",
        f"tickets/{US1}.md",
    ]
    assert all(r.startswith(FENCE_REASON) for _, r in report.skipped)


def test_ticket_of_fence_skipped_mission_goes_in_tickets_group(
    tmp_path: Path, block: str
):
    bad = "Scope.\n```md\n## inside\n```"
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block, overrides={"## Scope": bad})},
        {f"{US1}.md": ticket_text(block)},
    )
    assert run_plan(tmp_path).published == [US1]
    assert f"## {US1} " in doc_file(tmp_path, "tickets.raw.md")


def test_fenced_h1_and_h3_lines_do_not_split_the_section(tmp_path: Path, block: str):
    fenced = "Scope.\n\n```md\n# one\n### two\n```\n\nAfter the fence."
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block, overrides={"## Scope": fenced})},
        {},
    )
    assert run_plan(tmp_path).published == [MISSION_ID]
    l3 = doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    sliced = slice_section(l3, MISSION_ID)
    assert sliced is not None
    assert "### two\n```\n\nAfter the fence." in sliced
    assert list(section_map(l3)) == [MISSION_ID]


def test_l2_tables_equal_l3_tables(tmp_path: Path, block: str):
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block)},
        {f"{US1}.md": ticket_text(block)},
    )
    run_plan(tmp_path)
    for sid, group in ((MISSION_ID, MISSION_ID), (US1, MISSION_ID)):
        l2 = slice_section(doc_file(tmp_path, f"{group}.md"), sid)
        l3 = slice_section(doc_file(tmp_path, f"{group}.raw.md"), sid)
        assert l2 is not None and l3 is not None
        assert [normalize_table(t) for t in extract_tables(l2)] == [
            normalize_table(t) for t in extract_tables(l3)
        ]
        assert "mermaid" not in l2
    assert "Cut route-briefing time" in doc_file(tmp_path, f"{MISSION_ID}.md")
    assert "As a dispatcher" in doc_file(tmp_path, f"{MISSION_ID}.md")
    report = build.build_kb(tmp_path / ".kb")
    assert report.ok, report.errors


def test_crlf_and_nfd_inputs_render_like_lf_nfc(tmp_path: Path, block: str):
    text = mission_text(
        block, overrides={"## Summary": "Điều phối viên cần xem vùng cấm bay."}
    )
    lf, odd = tmp_path / "lf", tmp_path / "odd"
    write_repo(lf, {f"{MISSION_ID}.md": unicodedata.normalize("NFC", text)}, {})
    nfd = unicodedata.normalize("NFD", text).replace("\n", "\r\n")
    assert nfd != text
    write_repo(odd, {f"{MISSION_ID}.md": nfd}, {})
    for root in (lf, odd):
        assert run_plan(root).published == [MISSION_ID]
    for name in (f"{MISSION_ID}.md", f"{MISSION_ID}.raw.md", "_manifest.yaml"):
        assert doc_file(lf, name) == doc_file(odd, name)
    assert "vùng cấm bay" in doc_file(odd, f"{MISSION_ID}.raw.md")


def test_nothing_qualifies_removes_doc_and_index_entry(tmp_path: Path, block: str):
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    run_plan(tmp_path)
    assert (tmp_path / ".kb/demo-plan").is_dir()
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block, skip="## Scope")}, {})
    report = run_plan(tmp_path)
    assert report.published == [] and report.files_written == []
    assert not (tmp_path / ".kb/demo-plan").exists()
    index = models.load_yaml_model(tmp_path / ".kb/index.yaml", models.KBIndex)
    assert [d.id for d in index.docs] == []


def test_empty_missions_dir_publishes_nothing_and_writes_no_doc(tmp_path: Path):
    write_repo(tmp_path, {}, {})
    assert run_plan(tmp_path).published == []
    assert not (tmp_path / ".kb/demo-plan").exists()


def test_banner_and_manifest_title(tmp_path: Path, block: str, run_git):
    run_git(tmp_path, "init")
    run_git(tmp_path, "commit", "--allow-empty", "-m", "init")
    short = run_git(tmp_path, "rev-parse", "HEAD").strip()[:7]
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    run_plan(tmp_path)
    banner = f"> Generated by kb plan-ingest at {short} — do not edit by hand."
    assert banner in doc_file(tmp_path, f"{MISSION_ID}.md")
    assert banner in doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    manifest = models.load_yaml_model(
        tmp_path / ".kb/demo-plan/_manifest.yaml", models.Manifest
    )
    assert manifest.title == "demo — plan"
    assert manifest.revision == short
    assert {s.status for s in manifest.sections} == {"summarized"}
    assert all(s.summary for s in manifest.sections)
    index = models.load_yaml_model(tmp_path / ".kb/index.yaml", models.KBIndex)
    assert index.docs[0].tags == ["plan", "generated"]
    assert index.docs[0].revision == ""


def test_summary_is_first_sentence_of_summary_section(tmp_path: Path, block: str):
    text = mission_text(
        block, overrides={"## Summary": "First sentence here. Second one follows."}
    )
    write_repo(tmp_path, {f"{MISSION_ID}.md": text}, {})
    run_plan(tmp_path)
    manifest = models.load_yaml_model(
        tmp_path / ".kb/demo-plan/_manifest.yaml", models.Manifest
    )
    assert manifest.sections[0].summary == "First sentence here."


def test_rerun_prunes_dropped_mission_group(tmp_path: Path, block: str):
    other = "M-other"
    second = mission_text(block).replace(MISSION_ID, other)
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block), f"{other}.md": second},
        {},
    )
    run_plan(tmp_path)
    assert (tmp_path / ".kb/demo-plan" / f"{other}.md").exists()
    (tmp_path / "missions" / f"{other}.md").unlink()
    run_plan(tmp_path)
    assert not (tmp_path / ".kb/demo-plan" / f"{other}.md").exists()
    assert not (tmp_path / ".kb/demo-plan" / f"{other}.raw.md").exists()
    assert (tmp_path / ".kb/demo-plan" / f"{MISSION_ID}.md").exists()


def test_output_is_deterministic(tmp_path: Path, block: str):
    write_repo(
        tmp_path,
        {f"{MISSION_ID}.md": mission_text(block)},
        {f"{US1}.md": ticket_text(block)},
    )
    run_plan(tmp_path)
    first = doc_file(tmp_path, f"{MISSION_ID}.raw.md")
    run_plan(tmp_path)
    assert doc_file(tmp_path, f"{MISSION_ID}.raw.md") == first


def test_refuses_foreign_document_at_destination(tmp_path: Path, block: str):
    dest = tmp_path / ".kb/demo-plan"
    dest.mkdir(parents=True)
    (dest / "notes.md").write_text("# mine\n", encoding="utf-8")
    write_repo(tmp_path, {f"{MISSION_ID}.md": mission_text(block)}, {})
    with pytest.raises(planingest.PlanIngestError):
        run_plan(tmp_path)
    assert (dest / "notes.md").exists()


@pytest.mark.parametrize("repo_id", ["bad id", "a/b", ""])
def test_invalid_repo_id_raises(tmp_path: Path, repo_id: str):
    write_repo(tmp_path, {}, {})
    with pytest.raises(planingest.PlanIngestError):
        planingest.run(
            tmp_path,
            tmp_path / ".kb",
            repo_id,
            tmp_path / "missions",
            tmp_path / "tickets",
        )


def test_missing_missions_dir_raises(tmp_path: Path):
    (tmp_path / "tickets").mkdir()
    with pytest.raises(planingest.PlanIngestError, match="--missions-dir"):
        run_plan(tmp_path)


def test_unreadable_mission_raises(tmp_path: Path):
    write_repo(tmp_path, {}, {})
    (tmp_path / "missions" / "M-bad.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(planingest.PlanIngestError, match="M-bad.md"):
        run_plan(tmp_path)


# --- bug attachments ------------------------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_DOR_DONE = (
    "- [x] Steps reproduce the actual result on the stated environment\n"
    "- [x] Every open question has an owner"
)


def _bug_text(images: tuple[str, ...] = ("BUG-12/toast.png",)) -> str:
    from tests.test_buglint import _bug

    body = "\n".join(f"![toast]({src})" for src in images) or "N/A — none"
    return _bug(
        override={"## Attachments": body, "## Definition of Ready": _DOR_DONE},
        extra="",
    )


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _write_bug(root: Path, text: str, png: bytes | None = _PNG) -> None:
    write_repo(root, {}, {"bugs/BUG-12.md": text})
    if png is not None:
        folder = root / "tickets" / "bugs" / "BUG-12"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "toast.png").write_bytes(png)


def test_bug_publishes_with_sha_named_asset_and_rewritten_refs(tmp_path: Path):
    _write_bug(tmp_path, _bug_text())
    report = run_plan(tmp_path)
    assert report.published == ["BUG-12"] and not report.skipped
    name = f"{_sha(_PNG)}.png"
    assert (tmp_path / ".kb" / "demo-plan" / "assets" / name).read_bytes() == _PNG
    assert f"![toast](assets/{name})" in doc_file(tmp_path, "tickets.raw.md")
    assert "BUG-12/toast.png" not in doc_file(tmp_path, "tickets.raw.md")


def test_bug_l2_keeps_reproduction_prose_only(tmp_path: Path):
    _write_bug(tmp_path, _bug_text())
    run_plan(tmp_path)
    l2 = doc_file(tmp_path, "tickets.md")
    for kept in ("Steps to reproduce", "Expected result", "Actual result", "Summary"):
        assert f"### {kept}" in l2
    for dropped in ("Environment", "Impact", "Pre-conditions", "User Story"):
        assert f"### {dropped}" not in l2


def test_rerun_without_the_image_deletes_the_asset(tmp_path: Path):
    _write_bug(tmp_path, _bug_text())
    run_plan(tmp_path)
    assets = tmp_path / ".kb" / "demo-plan" / "assets"
    assert any(assets.iterdir())
    _write_bug(tmp_path, _bug_text(images=()), png=None)
    (tmp_path / "tickets" / "bugs" / "BUG-12" / "toast.png").unlink()
    report = run_plan(tmp_path)
    assert report.published == ["BUG-12"]
    assert not assets.exists() or not any(assets.iterdir())


def test_unreferenced_old_asset_is_pruned_and_shared_asset_kept(tmp_path: Path):
    _write_bug(tmp_path, _bug_text())
    run_plan(tmp_path)
    assets = tmp_path / ".kb" / "demo-plan" / "assets"
    stray = assets / ("0" * 64 + ".png")
    stray.write_bytes(b"old")
    run_plan(tmp_path)
    assert not stray.exists()
    assert (assets / f"{_sha(_PNG)}.png").exists()


def test_bug_with_missing_image_is_skipped(tmp_path: Path):
    _write_bug(tmp_path, _bug_text(), png=None)
    report = run_plan(tmp_path)
    assert report.published == []
    assert report.skipped and "not found" in report.skipped[0][1]


def test_bug_with_symlinked_image_is_skipped_and_not_copied(tmp_path: Path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(_PNG)
    _write_bug(tmp_path, _bug_text(), png=None)
    folder = tmp_path / "tickets" / "bugs" / "BUG-12"
    folder.mkdir()
    (folder / "toast.png").symlink_to(outside)
    report = run_plan(tmp_path)
    assert report.published == []
    assert "symlink" in report.skipped[0][1]
    assert not (tmp_path / ".kb" / "demo-plan" / "assets").exists()


def test_bug_with_symlinked_folder_is_skipped(tmp_path: Path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "toast.png").write_bytes(_PNG)
    _write_bug(tmp_path, _bug_text(), png=None)
    (tmp_path / "tickets" / "bugs" / "BUG-12").symlink_to(outside)
    report = run_plan(tmp_path)
    assert report.published == []
    assert "symlink" in report.skipped[0][1]


def test_assets_folder_does_not_break_ownership_check_or_cleanup(tmp_path: Path):
    _write_bug(tmp_path, _bug_text())
    run_plan(tmp_path)
    run_plan(tmp_path)  # second run: _check_owned sees manifest + assets/
    (tmp_path / "tickets" / "bugs" / "BUG-12.md").unlink()
    run_plan(tmp_path)  # nothing qualifies: whole doc dir (assets too) removed
    assert not (tmp_path / ".kb" / "demo-plan").exists()


def test_bug_image_listed_in_attachments_and_elsewhere_is_rewritten_everywhere(
    tmp_path: Path,
):
    from tests.test_buglint import _bug

    line = "![toast](BUG-12/toast.png)"
    text = _bug(
        override={
            "## Actual result": f"HTTP 500.\n{line}",
            "## Attachments": line,
            "## Definition of Ready": _DOR_DONE,
        }
    )
    _write_bug(tmp_path, text)
    assert run_plan(tmp_path).published == ["BUG-12"]
    name = f"{_sha(_PNG)}.png"
    for f in ("tickets.md", "tickets.raw.md"):
        body = doc_file(tmp_path, f)
        assert "BUG-12/toast.png" not in body
        assert body.count(f"![toast](assets/{name})") >= 1
    assert doc_file(tmp_path, "tickets.raw.md").count(f"assets/{name}") == 2


def test_bug_image_in_another_bugs_folder_is_skipped(tmp_path: Path):
    _write_bug(tmp_path, _bug_text(images=("BUG-13/x.png",)), png=None)
    other = tmp_path / "tickets" / "bugs" / "BUG-13"
    other.mkdir()
    (other / "x.png").write_bytes(_PNG)
    report = run_plan(tmp_path)
    assert report.published == []
    assert "not under 'BUG-12/'" in report.skipped[0][1]


def test_attach_checks_the_bug_folder_itself(tmp_path: Path):
    # defence in depth: lint already rejects this, _attach must too
    (tmp_path / "BUG-13").mkdir()
    (tmp_path / "BUG-13" / "x.png").write_bytes(_PNG)
    got = planingest._attach(_bug_text(images=("BUG-13/x.png",)), "BUG-12", tmp_path)
    assert isinstance(got, str) and "not under 'BUG-12/'" in got
