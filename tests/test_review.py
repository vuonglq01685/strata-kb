import pytest

from center_kb import gitio, models, quality
from center_kb.review import (
    approve_all_changed,
    approve_sections,
    changed_section_ids,
    check_approvable,
    resolve_reviewer,
)


def _statuses(kb, doc_id="demo-doc"):
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {s.id: s.status for s in manifest.sections}


def test_approve_flips_all_summarized_sections(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    assert report.flipped == ["1.1", "1.2"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_specific_section_only(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["1.1"], by="sme <sme@x>")
    assert report.flipped == ["1.1"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_skips_pending_and_reports_it(git_kb):
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(manifest_path, manifest)

    report = approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    assert report.flipped == ["1.2"]
    assert report.skipped_pending == ["1.1"]
    assert _statuses(git_kb["kb"])["1.1"] == "pending"


def test_approve_is_idempotent(git_kb):
    approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    report = approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    assert report.flipped == []
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_reports_missing_section(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["9.9"], by="sme <sme@x>")
    assert report.missing == ["9.9"]
    assert report.flipped == []


def test_approve_duplicate_missing_ids_reported_once(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["9.9", "9.9"], by="sme <sme@x>")
    assert report.missing == ["9.9"]


def test_approve_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="missing-doc"):
        approve_sections(git_kb["kb"], "missing-doc", by="sme <sme@x>")


def _dup_doc(kb):
    """Doc whose section ids repeat across parts (regulatory numbering restarts
    per part): id '1' and '1.1' each occur once in partA and once in partB.
    Mirrors ICAO Annex 8, where §-numbers restart inside every Part."""
    doc_dir = kb / "dup-doc"
    doc_dir.mkdir()
    for part in ("partA", "partB"):
        (doc_dir / f"{part}.md").write_text("## 1 X\n\ncondensed.\n", encoding="utf-8")
        (doc_dir / f"{part}.raw.md").write_text("## 1 X\n\nraw.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="dup-doc",
            title="Dup Doc",
            sections=[
                models.SectionEntry(id="1", title="A one", summary="s", status="summarized", file="partA"),
                models.SectionEntry(id="1.1", title="A oneone", summary="s", status="summarized", file="partA"),
                models.SectionEntry(id="1", title="B one", summary="s", status="summarized", file="partB"),
                models.SectionEntry(id="1.1", title="B oneone", summary="s", status="summarized", file="partB"),
            ],
        ),
    )


def _section_statuses(kb, doc_id):
    """Ordered (file, id) → status — does NOT collapse duplicate ids."""
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {(s.file, s.id): s.status for s in manifest.sections}


def test_approve_flips_every_duplicate_id_section(git_kb):
    _dup_doc(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "dup-doc", by="sme <sme@x>")
    assert report.flipped == ["1", "1.1", "1", "1.1"]
    assert set(_section_statuses(git_kb["kb"], "dup-doc").values()) == {"reviewed"}


def test_approve_duplicate_ids_idempotent(git_kb):
    _dup_doc(git_kb["kb"])
    approve_sections(git_kb["kb"], "dup-doc", by="sme <sme@x>")
    report = approve_sections(git_kb["kb"], "dup-doc", by="sme <sme@x>")
    assert report.flipped == []
    assert set(_section_statuses(git_kb["kb"], "dup-doc").values()) == {"reviewed"}


def test_approve_section_reaches_all_occurrences_of_id(git_kb):
    _dup_doc(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "dup-doc", ["1"], by="sme <sme@x>")
    assert report.flipped == ["1", "1"]
    assert _section_statuses(git_kb["kb"], "dup-doc") == {
        ("partA", "1"): "reviewed",
        ("partA", "1.1"): "summarized",
        ("partB", "1"): "reviewed",
        ("partB", "1.1"): "summarized",
    }


def _add_new_doc(kb, register_in_index: bool) -> None:
    """A doc present in the worktree but absent at every committed rev."""
    doc_dir = kb / "new-doc"
    doc_dir.mkdir()
    (doc_dir / "ch1.md").write_text("## 1.1 Intro\n\nCondensed intro.\n", encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text("## 1.1 Intro\n\nRaw intro.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="new-doc",
            title="New Doc",
            sections=[
                models.SectionEntry(
                    id="1.1",
                    title="Intro",
                    summary="Intro summary.",
                    status="summarized",
                    file="ch1",
                )
            ],
        ),
    )
    if register_in_index:
        index_path = kb / "index.yaml"
        index = models.load_yaml_model(index_path, models.KBIndex)
        index.docs.append(models.IndexEntry(id="new-doc", title="New Doc"))
        models.save_yaml_model(index_path, index)


def test_changed_ids_since_rev1(git_kb):
    # only §1.1 changed between rev1 and HEAD/worktree (see git_kb fixture)
    assert changed_section_ids(git_kb["kb"], "demo-doc", git_kb["rev1"]) == ["1.1"]


def test_changed_ids_catches_l2_only_edit(git_kb):
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airway record structure, route identifiers.",
            "airway record structure, REVISED identifiers.",
        ),
        encoding="utf-8",
    )
    assert changed_section_ids(git_kb["kb"], "demo-doc", "HEAD") == ["1.2"]


def test_changed_ids_new_doc_returns_none(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=False)
    assert changed_section_ids(git_kb["kb"], "new-doc", "HEAD") is None


def test_all_changed_flips_only_changed_sections(git_kb):
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"], by="sme <sme@x>")
    assert [(r.doc_id, r.flipped) for r in reports] == [("demo-doc", ["1.1"])]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_all_changed_nothing_changed_returns_empty(git_kb):
    assert approve_all_changed(git_kb["kb"], "HEAD", by="sme <sme@x>") == []
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_all_changed_new_doc_flips_all_its_summarized_sections(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], "HEAD", by="sme <sme@x>")
    by_doc = {r.doc_id: r.flipped for r in reports}
    assert by_doc == {"new-doc": ["1.1"]}
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "reviewed"}


def test_all_changed_single_doc_scope(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"], doc_id="demo-doc", by="sme <sme@x>")
    assert [r.doc_id for r in reports] == ["demo-doc"]
    # new-doc untouched despite being changed too
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "summarized"}


def test_all_changed_bad_rev_raises(git_kb):
    with pytest.raises(gitio.GitError):
        approve_all_changed(git_kb["kb"], "deadbeef1234", by="sme <sme@x>")


# --- check_approvable / resolve_reviewer / review record -------------------


def test_check_approvable_clean_kb_is_ok(git_kb):
    assert check_approvable(git_kb["kb"], ["demo-doc"]) == []


def test_check_approvable_refuses_dirty_tree(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nx\n", encoding="utf-8"
    )
    errs = check_approvable(git_kb["kb"], ["demo-doc"])
    assert errs and "commit .kb/demo-doc before approving" in errs[0]


def test_check_approvable_refuses_strict_build_errors(git_kb, run_git):
    from tests.conftest import TABLE

    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            TABLE, TABLE + "\n\n| X | Y |\n|---|---|\n| 1 | 2 |"
        ),
        encoding="utf-8",
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "fabricated table")
    errs = check_approvable(git_kb["kb"], ["demo-doc"])
    assert any("table" in e for e in errs)


def test_check_approvable_only_reports_this_doc(git_kb, run_git):
    other = git_kb["kb"] / "other"
    other.mkdir()
    (other / "f.md").write_text("## 1 A\n\n<!-- TODO:summarize 1 -->\n", encoding="utf-8")
    (other / "f.raw.md").write_text("## 1 A\n\nprose\n", encoding="utf-8")
    models.save_yaml_model(
        other / "_manifest.yaml",
        models.Manifest(
            id="other", title="O", sections=[models.SectionEntry(id="1", title="A", file="f")]
        ),
    )
    ipath = git_kb["kb"] / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs.append(models.IndexEntry(id="other", title="O", summary="s"))
    models.save_yaml_model(ipath, idx)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "other doc pending")
    assert check_approvable(git_kb["kb"], ["demo-doc"]) == []


def test_check_approvable_never_dirties_tree(git_kb, run_git):
    """R8: the gate's own strict build must not write token counts anywhere —
    not even into a passing, non-target doc — so approval never dirties the
    tree it just verified is clean."""
    kb = git_kb["kb"]
    other_dir = kb / "other-doc"
    other_dir.mkdir()
    (other_dir / "f.md").write_text("## 1 A\n\n<!-- TODO:summarize 1 -->\n", encoding="utf-8")
    (other_dir / "f.raw.md").write_text("## 1 A\n\nraw prose.\n", encoding="utf-8")
    models.save_yaml_model(
        other_dir / "_manifest.yaml",
        models.Manifest(id="other-doc", title="Other", sections=[
            models.SectionEntry(id="1", title="A", file="f")
        ]),
    )
    ipath = kb / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs.append(models.IndexEntry(id="other-doc", title="Other", summary="s"))
    models.save_yaml_model(ipath, idx)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "add other-doc")

    manifests = list(kb.rglob("_manifest.yaml"))
    before = {p: p.read_bytes() for p in manifests}
    assert check_approvable(kb, ["demo-doc"]) == []
    assert not gitio.is_dirty(git_kb["root"], kb.resolve())
    for p, content in before.items():
        assert p.read_bytes() == content


def test_check_approvable_pending_sibling_does_not_block(git_kb, run_git):
    """R9: a pending sibling section (a REAL pending section — TODO marker
    in L2, empty summary, status pending, exactly as `kb ingest` leaves an
    unsummarized section) must not block approving the doc's
    already-summarized sections — incremental approval is the documented
    workflow, and `skipped_pending` already exists to report it."""
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[1].status = "pending"
    manifest.sections[1].summary = ""
    models.save_yaml_model(manifest_path, manifest)
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed: airway record structure, route identifiers.",
            "<!-- TODO:summarize 1.2 -->",
        ),
        encoding="utf-8",
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "1.2 back to pending")
    assert check_approvable(git_kb["kb"], ["demo-doc"]) == []


def test_check_approvable_returns_unprefixed_build_error(git_kb, run_git):
    """A build error that names no known doc (e.g. a missing index.yaml)
    must never be silently dropped by the target-prefix filter — it is
    always blocking."""
    (git_kb["kb"] / "index.yaml").unlink()
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "drop index.yaml")
    errs = check_approvable(git_kb["kb"], ["demo-doc"])
    assert any("not found" in e and "index.yaml" in e for e in errs)


def test_resolve_reviewer_flag_then_git_config(git_kb):
    assert resolve_reviewer(git_kb["root"], "Ada <ada@x>") == "Ada <ada@x>"
    assert resolve_reviewer(git_kb["root"], None) == "test <test@test.local>"


def test_resolve_reviewer_fails_without_identity(tmp_path, run_git, monkeypatch):
    """Deterministic regardless of the dev machine's own git identity: force
    an empty global config and disable the system config, on top of the
    already-empty local config, so no layer can supply a name/email."""
    empty_gitconfig = tmp_path / "empty-gitconfig"
    empty_gitconfig.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty_gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "--local", "user.name", "")
    run_git(tmp_path, "config", "--local", "user.email", "")
    with pytest.raises(ValueError, match="--by"):
        resolve_reviewer(tmp_path, None)


def test_approve_writes_review_record(git_kb):
    from center_kb.mdutils import slice_section

    approve_sections(git_kb["kb"], "demo-doc", ["1.1"], by="sme <sme@x>")
    m = models.load_yaml_model(git_kb["kb"] / "demo-doc" / "_manifest.yaml", models.Manifest)
    rec = m.sections[0].reviewed
    l2 = (git_kb["kb"] / "demo-doc" / "ch1-records.md").read_text(encoding="utf-8")
    assert rec.by == "sme <sme@x>" and rec.at.endswith("Z")
    assert rec.l2_sha256 == quality.digest(slice_section(l2, "1.1"))
    assert m.sections[1].reviewed is None


def test_approve_dup_id_sections_hash_correct_occurrence(tmp_path):
    """Two `summarized` rows sharing an id in one file: each row's review
    record must hash ITS OWN heading occurrence, not always occurrence 0 —
    else the next strict build sees a false 'L2 changed after review'."""
    from center_kb.build import build_kb

    kb = tmp_path / ".kb"
    doc_dir = kb / "dup-review-doc"
    doc_dir.mkdir(parents=True)
    l2 = """## 1.1 Duplicate Section

Condensed occurrence one: designation and type fields covered here.

## 1.1 Duplicate Section

Condensed occurrence two: designation and level fields covered here.
"""
    l3 = """## 1.1 Duplicate Section

Full raw text of the first occurrence. Designation, type, level fields are documented in detail across several sentences so that the prose comfortably exceeds two hundred characters of length, matching prose overlap from the source text for the ratio and lexical checks to pass cleanly.

## 1.1 Duplicate Section

Full raw text of the second occurrence. Designation, type, level fields are documented in detail across several different sentences so that the prose comfortably exceeds two hundred characters of length too, matching prose overlap from the source text for the ratio and lexical checks to pass cleanly as well.
"""
    (doc_dir / "ch1.md").write_text(l2, encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text(l3, encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="dup-review-doc",
            title="Dup Review Doc",
            sections=[
                models.SectionEntry(
                    id="1.1", title="Duplicate Section",
                    summary="First occurrence summary of duplicate section fields.",
                    status="summarized", file="ch1",
                ),
                models.SectionEntry(
                    id="1.1", title="Duplicate Section",
                    summary="Second occurrence summary of duplicate section fields.",
                    status="summarized", file="ch1",
                ),
            ],
        ),
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(
            docs=[
                models.IndexEntry(
                    id="dup-review-doc", title="Dup Review Doc", summary="Dup doc for review test."
                )
            ]
        ),
    )
    approve_sections(kb, "dup-review-doc", by="sme <sme@x>")
    report = build_kb(kb, strict=True)
    assert not any("L2 changed after review" in e for e in report.errors)
    assert report.errors == []


def _add_hist_section(kb):
    manifest_path = kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    src = manifest.sections[0]
    manifest.sections.append(models.SectionEntry(
        id="hist.api", title="api — ticket history", summary="Tickets: 1.",
        status="summarized", file=src.file,
    ))
    models.save_yaml_model(manifest_path, manifest)
    l2 = kb / "demo-doc" / f"{src.file}.md"
    with l2.open("a", encoding="utf-8") as fh:
        fh.write("\n## hist.api api — ticket history\n\n```text\nT-1 | x\n```\n")


def test_whole_doc_approve_skips_machine_authored_hist_sections(git_kb):
    _add_hist_section(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    assert "hist.api" not in report.flipped
    assert report.skipped_machine == ["hist.api"]
    assert _statuses(git_kb["kb"])["hist.api"] == "summarized"


def test_naming_a_hist_section_still_approves_it(git_kb):
    _add_hist_section(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "demo-doc", ["hist.api"], by="sme <sme@x>")
    assert report.flipped == ["hist.api"]
    assert report.skipped_machine == []
