import os
import platform
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

from center_kb import models
from center_kb.build import build_kb
from center_kb.codeingest import core
from center_kb.mdutils import slice_section
from center_kb.summarize import collect_pending
from tests.fixtures_coderepo import build_code_repo


def _run(root: Path, **kw) -> core.CodeIngestReport:
    return core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", **kw
        )
    )


def test_scaffold_creates_pending_svc_sections_with_the_exact_marker(tmp_path):
    root = build_code_repo(tmp_path)
    report = _run(root, scaffold_svc=True)
    assert "svc.airspace-service" in report.scaffolded
    svc_dir = root / ".kb" / "demo-svc"
    l2 = (svc_dir / "services.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize svc.airspace-service -->" in l2
    manifest = models.load_yaml_model(svc_dir / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" for s in manifest.sections)


def test_scaffold_l3_holds_deterministic_code_evidence(tmp_path):
    # Test gap (task review): the original three assertions here were all
    # satisfied by document *structure*, not content -- "airspace-service"
    # appears in the `## svc.airspace-service airspace-service` heading
    # `_render_group` emits regardless of what follows it, and "```" is
    # emitted unconditionally even when both the "files (name-match
    # heuristic; absence proves nothing):" and "tables (name-match
    # heuristic; absence proves nothing):" evidence lists are "none".
    # This test would still pass with the
    # entire evidence *body* empty. Assert on real evidence instead: the
    # extractor-rendered image tag, and a real file path the L3
    # name-token match rule actually found for this service
    # ("src/airspace/service.py", from the fixture's own
    # src/airspace/service.py + docker-compose.yml "airspace-service:").
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")
    assert "image: airspace:1.0" in l3
    assert "src/airspace/service.py" in l3
    assert "|" not in l3


def test_scaffold_l3_tables_label_is_relabelled_as_a_name_match_heuristic(tmp_path):
    # R6 (Stage C task review, following Stage B handover item 2): a bare
    # "tables:" label followed by "- none" reads as the factual claim
    # "this service touches no tables" -- but _service_evidence()'s table
    # line is a same-name-token-superset match, which on a realistic repo
    # (a service named for what it does, a table for what it stores)
    # essentially never fires. On this fixture "airspace-service" (tokens
    # {airspace, service}) doesn't match "restrictive_airspace" (tokens
    # {restrictive, airspace}), so it renders "none" here too -- exactly
    # the case the old label misrepresented. Relabelled to say plainly
    # that the line is a heuristic and that absence proves nothing; the
    # rendered list shape ("  - <id>" / "  - none" inside the fenced
    # block) is otherwise unchanged.
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")
    assert "tables (name-match heuristic; absence proves nothing):" in l3
    assert "\ntables:\n" not in l3
    assert "  - none" in l3


def test_scaffold_l3_files_label_is_relabelled_as_a_name_match_heuristic(tmp_path):
    # Minor 7 (task review, extending R6): "files:" is backed by the exact
    # same same-name-token-superset heuristic as "tables:" (both call
    # _name_tokens() and compare via `wanted <= ...`), so leaving "files:"
    # bare while relabelling "tables:" alone made two lines in the same
    # fenced block claim different epistemic strength from the identical
    # rule -- a service whose files don't happen to follow the directory
    # naming convention would render "files:" / "- none", reading as "this
    # service has no files" just as wrongly as the old "tables:" did.
    # Relabelled the same way; rendered list shape unchanged.
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")
    assert "files (name-match heuristic; absence proves nothing):" in l3
    assert "\nfiles:\n" not in l3
    # airspace-service's own evidence has a real, non-"none" files match
    # (src/airspace/service.py) -- prove the relabelled line still lists
    # real matches, not just the "- none" case the tables test covers.
    assert "src/airspace/service.py" in l3


def test_scaffolded_sections_are_visible_to_collect_pending(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    pending = collect_pending(root / ".kb", "demo-svc")
    assert {p.section_id for p in pending} >= {"svc.airspace-service", "svc.postgres"}


def test_svc_index_entry_is_tagged_code_curated(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-svc")
    assert entry.tags == ["code", "curated"]


# Final review, Important 2's other half: `_upsert_index_entry`'s preserve
# logic must not stop a genuinely NEW `-svc` document's index entry from
# getting its placeholder summary on first scaffold -- the guard added
# there only ever protects a PRE-EXISTING entry's already-drafted summary
# (`entry is None` skips the guard entirely and always writes the
# placeholder passed in). Same check for the `-code` document's own entry
# on a second, ordinary run, since both documents share `_upsert_index_
# entry` and `-code`'s placeholder is passed fresh on every run too.
def test_new_svc_and_code_index_entries_get_their_placeholder_summary(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    svc_entry = next(d for d in index.docs if d.id == "demo-svc")
    code_entry = next(d for d in index.docs if d.id == "demo-code")
    assert svc_entry.summary == "Curated service knowledge for the demo repository."
    assert code_entry.summary == "Generated code knowledge for the demo repository."

    # A second, ordinary run (nothing drafted yet) must still show the
    # same placeholder for both documents -- proving the guard's "equal to
    # the caller's own placeholder" branch is exercised, not just its
    # "empty" branch.
    _run(root, scaffold_svc=True)
    index_again = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    svc_entry_again = next(d for d in index_again.docs if d.id == "demo-svc")
    code_entry_again = next(d for d in index_again.docs if d.id == "demo-code")
    assert svc_entry_again.summary == svc_entry.summary
    assert code_entry_again.summary == code_entry.summary


def test_second_run_refreshes_l3_only_and_never_touches_reviewed_l2(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    l2_path.write_text(
        l2_path.read_text(encoding="utf-8").replace(
            "<!-- TODO:summarize svc.airspace-service -->",
            "Owns airspace approval decisions.",
        ),
        encoding="utf-8",
    )
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        if sec.id == "svc.airspace-service":
            sec.status = "reviewed"
            sec.summary = "Owns airspace approval decisions."
    models.save_yaml_model(manifest_path, manifest)

    _run(root, scaffold_svc=True)

    assert "Owns airspace approval decisions." in l2_path.read_text(encoding="utf-8")
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    reviewed = next(s for s in manifest.sections if s.id == "svc.airspace-service")
    assert reviewed.status == "reviewed"
    assert reviewed.summary == "Owns airspace approval decisions."


def test_changed_evidence_under_a_reviewed_section_raises_stale_risk(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    manifest_path = root / ".kb" / "demo-svc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = "Reviewed by a human."
    models.save_yaml_model(manifest_path, manifest)

    compose = root / "docker-compose.yml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace("8080:8080", "9090:9090"),
        encoding="utf-8",
    )
    report = _run(root, scaffold_svc=True)
    assert "svc.airspace-service" in report.stale_risk


def test_service_removed_from_code_is_reported_as_orphan_not_deleted(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    compose = root / "docker-compose.yml"
    compose.write_text(
        "services:\n  airspace-service:\n    image: airspace:1.0\n", encoding="utf-8"
    )
    report = _run(root, scaffold_svc=True)
    assert "svc.postgres" in report.orphans
    l2 = (root / ".kb" / "demo-svc" / "services.md").read_text(encoding="utf-8")
    assert "## svc.postgres" in l2


def test_scaffolded_state_fails_build_without_allow_pending_and_passes_with_it(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    strict = build_kb(root / ".kb")
    assert not strict.ok
    assert any("demo-svc" in e for e in strict.errors)
    lenient = build_kb(root / ".kb", allow_pending=True)
    assert lenient.ok


def test_code_document_still_builds_clean_when_scaffold_is_not_requested(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root)
    assert not (root / ".kb" / "demo-svc").exists()
    assert build_kb(root / ".kb").ok


# ---------------------------------------------------------------------------
# Review round 2 — Controller Ruling R42 (Critical 1): the evidence builder
# must never read file *content*, only paths. A test that only greps for one
# known secret string would pass against a rewritten leak, so this also
# pins the evidence block's grammar structurally: every
# "files (name-match heuristic; absence proves nothing):" line is exactly
# "  - <path>", nothing appended after the path.
# ---------------------------------------------------------------------------


def test_scaffold_never_reads_file_content_into_l3_evidence(tmp_path):
    root = build_code_repo(tmp_path)
    # File names deliberately contain BOTH of svc.airspace-service's own
    # name tokens ("airspace" and "service") so they are genuinely matched
    # as evidence by the (also just-fixed, Important 3) file selector —
    # otherwise this test would pass merely because the planted files
    # were never selected at all, without exercising Critical 1's fix.
    # Content is comment-shaped on purpose: the reviewer's finding was
    # specifically that a *comment-shaped* first line defeats the header
    # filter (the header reader only ever returned a line shaped like a
    # comment/docstring in the first place) — a name-prefix dotenv guard
    # wouldn't help either, since "airspace-service.env" doesn't start
    # with ".env".
    (root / "airspace-service.env").write_text(
        "# service account password: s3cr3t-p4ss\n", encoding="utf-8"
    )
    secret_file = root / "src" / "airspace" / "service_conn.py"
    secret_file.write_text(
        "# connects with postgres://admin:hunter2@prod-db:5432/airspace\n",
        encoding="utf-8",
    )
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")

    # Prove the planted files were actually selected as evidence (their
    # bare paths must appear) — otherwise the assertions below would pass
    # vacuously if the file selector simply hadn't matched them at all.
    assert "airspace-service.env" in l3
    assert "src/airspace/service_conn.py" in l3

    # The reviewer's exact reproduction strings.
    assert "hunter2" not in l3
    assert "s3cr3t-p4ss" not in l3
    assert "password" not in l3

    # Stronger than a secret-string grep (a test that only checks for
    # "hunter2" would pass against a rewritten leak): no planted file's
    # content ever appears in the document at all, and the evidence
    # block's "files (name-match heuristic; absence proves nothing):" lines
    # are structurally closed to a bare path — nothing could be appended
    # after it even by accident.
    assert "connects with postgres" not in l3
    assert "service account password" not in l3
    for line in l3.splitlines():
        if line.startswith("  - ") and ("/" in line or line.strip("- ") == "none"):
            assert re.fullmatch(r"  - (\S+|none)", line), (
                f"unexpected content appended after a path in evidence line: {line!r}"
            )


# ---------------------------------------------------------------------------
# Review round 2 — Controller Ruling R43 (Critical 2): a human's own
# subheading inside a reviewed L2 body must never truncate anything after
# it. This is the reviewer's exact reproduction.
# ---------------------------------------------------------------------------


def test_reviewed_l2_subheadings_are_never_truncated(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    human_body = (
        "Owns airspace approval decisions.\n"
        "\n"
        "## Ownership\n"
        "\n"
        "Team Foxtrot owns this. Escalate to the on-call rota.\n"
        "\n"
        "### Runbook\n"
        "\n"
        "Restart via `make restart`.\n"
    )
    l2_path.write_text(
        l2_path.read_text(encoding="utf-8").replace(
            "<!-- TODO:summarize svc.airspace-service -->", human_body
        ),
        encoding="utf-8",
    )
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        if sec.id == "svc.airspace-service":
            sec.status = "reviewed"
            sec.summary = "Owns airspace approval decisions."
    models.save_yaml_model(manifest_path, manifest)

    report = _run(root, scaffold_svc=True)

    after = l2_path.read_text(encoding="utf-8")
    assert "Team Foxtrot owns this. Escalate to the on-call rota." in after
    assert "## Ownership" in after
    assert "### Runbook" in after
    assert "Restart via `make restart`." in after
    assert report.warnings == []
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    reviewed = next(s for s in manifest.sections if s.id == "svc.airspace-service")
    assert reviewed.status == "reviewed"
    assert reviewed.summary == "Owns airspace approval decisions."


def test_stray_heading_with_no_manifest_entry_refuses_rather_than_drops(tmp_path):
    """Ruling R43's refuse-and-error fallback: a case the upsert/orphan
    paths genuinely cannot represent (a real heading in services.md with
    no corresponding _manifest.yaml entry to explain its status/summary)
    must raise, naming the section, rather than silently guessing."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    manifest_path = root / ".kb" / "demo-svc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections = [s for s in manifest.sections if s.id != "svc.postgres"]
    models.save_yaml_model(manifest_path, manifest)
    # services.md still has the (now unexplained) heading + body for
    # svc.postgres; docker-compose.yml still produces it too this run.

    with pytest.raises(core.CodeIngestError, match="svc.postgres"):
        _run(root, scaffold_svc=True)

    # Nothing was overwritten by the refused run.
    l2 = (root / ".kb" / "demo-svc" / "services.md").read_text(encoding="utf-8")
    assert "## svc.postgres" in l2


def test_missing_services_md_self_heals_from_manifest_summary(tmp_path):
    """Important 4: a missing services.md must not wipe human status/summary
    that is still intact in the manifest."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = f"Human summary for {sec.id}."
    models.save_yaml_model(manifest_path, manifest)
    (svc_dir / "services.md").unlink()

    _run(root, scaffold_svc=True)

    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        assert sec.status == "reviewed"
        assert sec.summary == f"Human summary for {sec.id}."
    l2 = (svc_dir / "services.md").read_text(encoding="utf-8")
    assert "Human summary for svc.airspace-service." in l2
    assert "Human summary for svc.postgres." in l2


def test_doc_id_colliding_with_scaffold_svc_output_is_rejected(tmp_path):
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc",
            repo_id="demo", scaffold_svc=True,
        ))
    assert not (root / ".kb" / "demo-svc").exists()


# ---------------------------------------------------------------------------
# Review round 2 — Important 3: token-overlap over-matches on any single
# shared token. Pin the corrected (subset-containment) matching rule with a
# real test, since the existing evidence test passes even with the whole
# matcher deleted.
# ---------------------------------------------------------------------------


def test_service_evidence_requires_every_name_token_not_just_one(tmp_path):
    root = build_code_repo(tmp_path)
    (root / "src" / "billing").mkdir(parents=True)
    (root / "src" / "billing" / "service.py").write_text("", encoding="utf-8")
    (root / "src" / "notification").mkdir(parents=True)
    (root / "src" / "notification" / "service.py").write_text("", encoding="utf-8")
    compose = root / "docker-compose.yml"
    compose.write_text(
        compose.read_text(encoding="utf-8")
        + "  billing-service:\n    image: billing:1.0\n"
        + "  notification-service:\n    image: notify:1.0\n"
        + "  cache-db:\n    image: redis:7\n",
        encoding="utf-8",
    )
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")

    airspace_slice = slice_section(l3, "svc.airspace-service")
    billing_slice = slice_section(l3, "svc.billing-service")
    notif_slice = slice_section(l3, "svc.notification-service")
    cache_db_slice = slice_section(l3, "svc.cache-db")

    # True positives still hold: every name token is required, and each
    # service's own path satisfies that.
    assert "src/airspace/service.py" in airspace_slice
    assert "src/billing/service.py" in billing_slice
    assert "src/notification/service.py" in notif_slice

    # False positives (a bare shared token) are gone.
    assert "src/billing/service.py" not in airspace_slice
    assert "src/notification/service.py" not in airspace_slice
    assert "src/airspace/service.py" not in billing_slice
    assert "src/notification/service.py" not in billing_slice
    assert "src/airspace/service.py" not in notif_slice
    assert "src/billing/service.py" not in notif_slice

    # cache-db must not claim every SQL migration / db.* table purely
    # because its own name contains the token "db".
    assert "db.restrictive_airspace" not in cache_db_slice
    assert "V1__create_airspace.sql" not in cache_db_slice
    assert "V2__add_effective_date.sql" not in cache_db_slice


# ---------------------------------------------------------------------------
# Review round 2 — Important 5: a wrong-shaped index.yaml or -code
# _manifest.yaml must degrade (named warning), never crash the command.
# ---------------------------------------------------------------------------


def test_wrong_shaped_index_yaml_degrades_instead_of_crashing(tmp_path):
    root = build_code_repo(tmp_path)
    (root / ".kb").mkdir(parents=True, exist_ok=True)
    (root / ".kb" / "index.yaml").write_text("- a\n- b\n", encoding="utf-8")

    report = _run(root)

    assert report.doc_id == "demo-code"
    assert any("index.yaml" in w for w in report.warnings)
    # Left untouched, not overwritten with a fresh (lossy) empty index.
    assert (root / ".kb" / "index.yaml").read_text(encoding="utf-8") == "- a\n- b\n"


def test_wrong_shaped_existing_code_manifest_is_refused_not_degraded(tmp_path):
    """Superseded by reviewer G-1: this used to degrade (warn, then
    silently overwrite with a fresh manifest). Nobody can tell whose
    document an unreadable manifest belongs to, so it is refused instead,
    and the existing (wrong-shaped) manifest is left untouched."""
    root = build_code_repo(tmp_path)
    _run(root)
    manifest_path = root / ".kb" / "demo-code" / "_manifest.yaml"
    manifest_path.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(core.CodeIngestError) as excinfo:
        _run(root)

    assert "did not generate" in str(excinfo.value)
    assert any("_manifest.yaml" in w for w in excinfo.value.report.warnings)
    assert manifest_path.read_text(encoding="utf-8") == "- a\n- b\n"


# ---------------------------------------------------------------------------
# Review round 2 — the durable form of Ruling R23: `CodeIngestOptions.
# __post_init__` normalises repo_root/kb_dir/db_paths for *every* caller,
# not just the CLI.
# ---------------------------------------------------------------------------


def test_options_post_init_resolves_relative_kb_dir_against_cwd(tmp_path, monkeypatch):
    root = build_code_repo(tmp_path)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=Path("out/.kb"), doc_id="demo-code", repo_id="demo",
    )
    assert opts.kb_dir == (other_cwd / "out" / ".kb").resolve()

    core.run(opts)
    assert (other_cwd / "out" / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not (root / "out").exists()


def test_options_post_init_resolves_relative_db_paths_against_repo_root(tmp_path, monkeypatch):
    root = build_code_repo(tmp_path)
    con = sqlite3.connect(root / "only.db")
    con.execute("CREATE TABLE widgets (id INTEGER)")
    con.commit()
    con.close()
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo",
        db_paths=(Path("only.db"),),
    )
    assert opts.db_paths == ((root / "only.db").resolve(),)


# ---------------------------------------------------------------------------
# Review round 3 — Important 1: a known svc.* heading id occurring MORE
# THAN ONCE in services.md silently truncates content, exactly like the
# original Critical 2 defect, and is not caught by the stray-heading check
# alone (every id involved IS in the manifest). Three reviewer reproductions.
# ---------------------------------------------------------------------------


def test_reviewed_body_quoting_another_known_id_as_heading_refuses(tmp_path):
    """A "See also" line inside one reviewed section that happens to look
    like a real heading for a *different*, also-reviewed section must not
    silently delete that other section's prose."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    text = l2_path.read_text(encoding="utf-8")
    text = text.replace(
        "<!-- TODO:summarize svc.airspace-service -->",
        "Owns airspace approval decisions.\n\n"
        "## svc.postgres See also\n\n"
        "The primary datastore for restricted airspace records.",
    )
    text = text.replace(
        "<!-- TODO:summarize svc.postgres -->",
        "Stores relational data for the platform.",
    )
    l2_path.write_text(text, encoding="utf-8")

    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = f"Reviewed: {sec.id}"
    models.save_yaml_model(manifest_path, manifest)

    with pytest.raises(core.CodeIngestError, match="svc.postgres"):
        _run(root, scaffold_svc=True)

    # Nothing was overwritten by the refused run.
    after = l2_path.read_text(encoding="utf-8")
    assert "Stores relational data for the platform." in after


def test_reviewed_body_repeating_its_own_id_as_heading_refuses(tmp_path):
    """A section that repeats its own id as a "heading" partway through its
    body must not silently lose everything written after the repeat — this
    needs no second section at all."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    l2_path.write_text(
        l2_path.read_text(encoding="utf-8").replace(
            "<!-- TODO:summarize svc.airspace-service -->",
            "Owns airspace approval decisions.\n\n"
            "## svc.airspace-service duplicate heading\n\n"
            "This should never be silently dropped.",
        ),
        encoding="utf-8",
    )
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        if sec.id == "svc.airspace-service":
            sec.status = "reviewed"
            sec.summary = "Owns airspace approval decisions."
    models.save_yaml_model(manifest_path, manifest)

    with pytest.raises(core.CodeIngestError, match="svc.airspace-service"):
        _run(root, scaffold_svc=True)


def test_fenced_block_quoting_a_real_heading_refuses(tmp_path):
    """A fenced code block that quotes a real heading verbatim (e.g.
    documenting the file format itself) must not be mistaken for an actual
    section break just because the line inside the fence matches the
    heading grammar byte-for-byte."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    l2_path.write_text(
        l2_path.read_text(encoding="utf-8").replace(
            "<!-- TODO:summarize svc.airspace-service -->",
            "Owns airspace approval decisions.\n\n"
            "Example of another section's heading:\n\n"
            "```markdown\n"
            "## svc.postgres postgres\n"
            "```\n",
        ),
        encoding="utf-8",
    )
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = f"Reviewed: {sec.id}"
    models.save_yaml_model(manifest_path, manifest)

    with pytest.raises(core.CodeIngestError, match="svc.postgres"):
        _run(root, scaffold_svc=True)


# ---------------------------------------------------------------------------
# Review round 3 — Important 2: the -svc collision guard must fire even when
# THIS run does not request --scaffold-svc — the unguarded half was the
# more destructive one (whole curated files deleted by the stale-.md prune).
# ---------------------------------------------------------------------------


def test_doc_id_collision_guard_fires_even_without_scaffold_svc(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    # A curated file code-ingest itself never produces (Stage C's
    # `kb svc note` territory) — proves the *guard*, not just the prune,
    # protects it.
    (svc_dir / "flows.md").write_text(
        "# demo-svc\n\nHuman-authored flow notes.\n", encoding="utf-8"
    )
    original_services_md = (svc_dir / "services.md").read_text(encoding="utf-8")
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")

    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc", repo_id="demo",
        ))

    assert (svc_dir / "flows.md").read_text(encoding="utf-8") == (
        "# demo-svc\n\nHuman-authored flow notes.\n"
    )
    assert (svc_dir / "services.md").read_text(encoding="utf-8") == original_services_md
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest


# ---------------------------------------------------------------------------
# Review round 3 — folded item: CodeIngestError must carry whatever partial
# CodeIngestReport existed at the point of failure, so a caller can surface
# warnings already collected instead of only the exception's own message.
# ---------------------------------------------------------------------------


def test_codeingest_error_carries_partial_report_with_warnings(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    (root / ".kb" / "demo-svc" / "_manifest.yaml").write_text(
        "- a\n- b\n", encoding="utf-8"
    )

    with pytest.raises(core.CodeIngestError) as excinfo:
        _run(root, scaffold_svc=True)

    exc = excinfo.value
    assert exc.report is not None
    assert any("could not read" in w for w in exc.report.warnings)
    # The -code document's own files were already written before the
    # later --scaffold-svc refusal (a partial success, not a full failure).
    assert exc.report.files_written


# ---------------------------------------------------------------------------
# Review round 4 — Ruling R46a: the -svc collision guard keyed on exact,
# case-sensitive string equality between opts.doc_id and *this run's*
# repo_id + "-svc" — two spellings walked around it and reproduced the
# original destruction verbatim. Round 4 made the guard two-part: a name
# check (any doc_id whose casefolded form ends with "-svc") and a
# destination check (the target directory already holds curated markers,
# regardless of doc_id's spelling). A *third* round of bypasses (a trailing
# separator/dot) showed round 4's name check was still a raw-string
# comparison; Controller Ruling R47 (below, and in this file further down)
# replaces it with a resolved-path comparison against *this run's own*
# reserved <repo_id>-svc slot, and narrows its scope accordingly — it no
# longer blanket-refuses any doc_id merely resembling the convention for an
# unrelated repo_id (see the two tests immediately below).
# ---------------------------------------------------------------------------


def test_doc_id_collision_guard_catches_a_different_repo_id(tmp_path):
    """Bypass 1: doc_id="demo-svc" with a DIFFERENT repo_id ("other") used
    to sail past the old `doc_id == f"{repo_id}-svc"` check entirely."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    (svc_dir / "flows.md").write_text(
        "# demo-svc\n\nHuman-authored flow notes.\n", encoding="utf-8"
    )
    original_services_md = (svc_dir / "services.md").read_text(encoding="utf-8")
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")

    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc", repo_id="other",
        ))

    assert (svc_dir / "flows.md").read_text(encoding="utf-8") == (
        "# demo-svc\n\nHuman-authored flow notes.\n"
    )
    assert (svc_dir / "services.md").read_text(encoding="utf-8") == original_services_md
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest


def test_doc_id_collision_guard_catches_a_different_case_spelling(tmp_path):
    """Bypass 2: doc_id="Demo-svc" used to fail the old case-sensitive `==`
    check even though it physically aliases "demo-svc" on a
    case-insensitive filesystem."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    (svc_dir / "flows.md").write_text(
        "# demo-svc\n\nHuman-authored flow notes.\n", encoding="utf-8"
    )
    original_services_md = (svc_dir / "services.md").read_text(encoding="utf-8")
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")

    with pytest.raises(core.CodeIngestError, match="Demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="Demo-svc", repo_id="demo",
        ))

    assert (svc_dir / "flows.md").read_text(encoding="utf-8") == (
        "# demo-svc\n\nHuman-authored flow notes.\n"
    )
    assert (svc_dir / "services.md").read_text(encoding="utf-8") == original_services_md
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest


def test_name_check_matches_via_resolved_path_with_no_existing_destination(tmp_path):
    """Isolates the *name* half of the guard from the destination half:
    the target has never been scaffolded at all (the destination check
    would find no curated markers and return False), so only the
    reserved-<repo_id>-svc-path comparison can be refusing this — and it
    must do so via resolved-path equality, not a string suffix check on
    `opts.doc_id` (Controller Ruling R47a): "demo-svc/" is one of the
    four reported bypass spellings, and pathlib already drops its
    trailing separator at construction time, before `.resolve()` even
    runs — proving the comparison never touches the raw string."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc/",
            repo_id="demo",
        ))
    assert not (root / ".kb" / "demo-svc").exists()


def test_name_check_fires_for_any_repo_id_not_just_this_runs_own_slot(tmp_path):
    """Controller Ruling R48a(2): round 5 first narrowed the name check to
    only *this run's own* `<repo_id>-svc` slot (dropped here because that
    narrowing, combined with dropping the index "curated" tag in the same
    round, left `--repo-id other --doc-id demo-svc` covered by the
    destination check alone — and that check had no signal for a
    freshly-scaffolded document at the time). The blanket "-svc is
    reserved, full stop, regardless of repo_id" check is restored: a
    doc_id ending in "-svc" for an *unrelated* repo_id is refused even
    though the target has never held curated content — matching round
    4's original coverage, now computed on the resolved final component
    rather than the raw string."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="mismatched-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="mismatched-svc",
            repo_id="other",
        ))
    assert not (root / ".kb" / "mismatched-svc").exists()


def test_destination_check_protects_a_curated_dir_whose_name_does_not_end_in_svc(tmp_path):
    """The destination check is the durable half: it protects a curated
    document regardless of naming convention, not just the "-svc" suffix
    the name check recognises."""
    kb_dir = tmp_path / ".kb"
    curated_dir = kb_dir / "weird-name"
    curated_dir.mkdir(parents=True)
    (curated_dir / "flows.md").write_text(
        "# weird-name\n\nHuman flow notes.\n", encoding="utf-8"
    )
    manifest = models.Manifest(
        id="weird-name",
        title="curated",
        sections=[
            models.SectionEntry(
                id="flow.approval", title="approval", summary="x",
                status="reviewed", file="flows",
            ),
        ],
    )
    models.save_yaml_model(curated_dir / "_manifest.yaml", manifest)
    index = models.KBIndex(
        docs=[models.IndexEntry(id="weird-name", title="curated", tags=["code", "curated"])]
    )
    models.save_yaml_model(kb_dir / "index.yaml", index)

    with pytest.raises(core.CodeIngestError, match="weird-name"):
        core.run(core.CodeIngestOptions(
            repo_root=tmp_path, kb_dir=kb_dir, doc_id="weird-name", repo_id="demo",
        ))

    assert (curated_dir / "flows.md").read_text(encoding="utf-8") == (
        "# weird-name\n\nHuman flow notes.\n"
    )


# ---------------------------------------------------------------------------
# Review round 4 — Ruling R46b: human prose written between the banner and
# the first section heading is otherwise invisible to every slice (they all
# start AT a heading) and was silently dropped on every re-render.
# ---------------------------------------------------------------------------


def test_human_preamble_before_the_first_heading_is_preserved(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    banner_line = (
        "> Responsibility text is human-owned. L3 code evidence "
        "regenerated at unknown-commit."
    )
    preamble = "This document curates the platform's services. See the team wiki for context."
    text = l2_path.read_text(encoding="utf-8")
    assert banner_line + "\n" in text
    text = text.replace(banner_line + "\n", banner_line + "\n\n" + preamble + "\n", 1)
    l2_path.write_text(text, encoding="utf-8")

    report = _run(root, scaffold_svc=True)

    after = l2_path.read_text(encoding="utf-8")
    assert preamble in after
    assert report.warnings == []

    # Idempotent: a further run doesn't drift or duplicate the preamble.
    _run(root, scaffold_svc=True)
    assert l2_path.read_text(encoding="utf-8") == after


# ---------------------------------------------------------------------------
# Controller Ruling R47 — round 4's two-part guard was still defeated, three
# rounds running, by the same class of bug: every comparison (the name
# check's `casefold().endswith("-svc")`, the destination check's
# `d.id == doc_id` index lookup) compared the raw `opts.doc_id` *string*,
# while `Path(kb_dir) / doc_id` already resolves to the real curated
# directory for a doc_id with a trailing separator, a trailing dot, or a
# doubled separator. Every comparison in the guard is now against that one
# resolved directory instead, never against `opts.doc_id` itself.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc_id", ["demo-svc/", "demo-svc.", "demo-svc/.", "demo-svc//"]
)
def test_all_four_reported_trailing_spellings_are_blocked_from_the_curated_dir(
    tmp_path, doc_id
):
    """Ruling R47a's exact reproduction matrix: a plain (non-scaffold) run
    naming one of the four reported bypass spellings as --doc-id, against
    an already-curated demo-svc/. None of these four strings end in the
    literal substring "-svc" (round 4's name check) or equal "demo-svc"
    under `==` (round 4's destination-check index lookup) — but
    `Path(kb_dir) / doc_id` already resolves to the real curated directory
    for every one of them."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    original_services_md = (svc_dir / "services.md").read_text(encoding="utf-8")
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")

    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id=doc_id, repo_id="demo",
        ))

    assert (svc_dir / "services.md").read_text(encoding="utf-8") == original_services_md
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest
    # The reported symptom: no duplicate index.yaml entry for one directory.
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    assert sorted(d.id for d in index.docs) == ["demo-code", "demo-svc"]


def test_dotdot_segment_resolving_back_to_the_reserved_slot_is_blocked(tmp_path):
    """Attack beyond the four reported spellings: an interior '..' segment
    that lexically cancels back out to the reserved <repo_id>-svc slot."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="a/../demo-svc",
            repo_id="demo",
        ))


def test_mixed_case_combined_with_trailing_separator_is_blocked(tmp_path):
    """Attack beyond the four reported spellings: combining round 4's
    case-insensitive-filesystem bypass with this round's separator bypass
    in a single doc_id."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    original_manifest = (svc_dir / "_manifest.yaml").read_text(encoding="utf-8")
    with pytest.raises(core.CodeIngestError, match="Demo-Svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="Demo-Svc/",
            repo_id="demo",
        ))
    assert (svc_dir / "_manifest.yaml").read_text(encoding="utf-8") == original_manifest


def test_doc_id_absolute_path_cannot_escape_kb_dir(tmp_path):
    """Attack beyond the four reported spellings: pathlib's `/` operator
    discards the left operand entirely when the right one is absolute, so
    `kb_dir / doc_id` can name a directory completely outside --kb-dir."""
    root = build_code_repo(tmp_path)
    outside = tmp_path / "outside"
    with pytest.raises(core.CodeIngestError, match="outside"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb",
            doc_id=str(outside / "evil"), repo_id="demo",
        ))
    assert not outside.exists()


def test_doc_id_dotdot_escape_cannot_leave_kb_dir(tmp_path):
    """Attack beyond the four reported spellings: a doc_id whose own '..'
    walks entirely out of --kb-dir, not just back to another doc inside it."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="outside"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="../escape",
            repo_id="demo",
        ))
    assert not (root / "escape").exists()


@pytest.mark.parametrize("doc_id", ["", ".", "/"])
def test_doc_id_that_is_empty_or_names_kb_dir_itself_is_rejected(tmp_path, doc_id):
    """Attack beyond the four reported spellings: a doc_id that resolves
    to --kb-dir itself (empty string, ".") or escapes it outright ("/",
    which on Windows resolves to the current drive's root) must be
    rejected before anything is created."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id=doc_id, repo_id="demo",
        ))
    assert not (root / ".kb").exists()


@pytest.mark.parametrize("doc_id", ["demo-code ", "demo-code."])
def test_doc_id_with_trailing_space_or_dot_is_rejected_up_front(tmp_path, doc_id):
    """Controller Ruling R47d: a --doc-id ending in a trailing space or dot
    is never normalised by pathlib and was never validated before use.
    Windows silently strips a trailing space/dot from the *final*
    component of a single filesystem call — so doc_dir.mkdir() quietly
    created "demo-code", not "demo-code " — but does not apply that
    stripping to an *interior* component of a longer path, so the nested
    `_write_group` write right after it looked up the literal
    space-suffixed name, found nothing, and raised a raw
    FileNotFoundError instead of a CodeIngestError."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="trailing"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id=doc_id, repo_id="demo",
        ))
    assert not any((root / ".kb").glob("demo-code*"))


def test_manifest_read_for_the_destination_check_is_not_duplicated(tmp_path):
    """Controller Ruling R47e: `_is_curated_destination()` used to call
    `_load_manifest_guarded()` on the -code document's own _manifest.yaml,
    and run() called it again right after, purely to preserve token
    counts — a wrong-shaped file then emitted the identical "could not
    read" warning twice instead of the one review round 2 intended.
    Reviewer G-1 now refuses this destination outright rather than
    degrading and overwriting it, but the single-read guarantee still
    matters: the "could not read" warning must still appear exactly once,
    on the partial report the refusal carries."""
    root = build_code_repo(tmp_path)
    _run(root)
    manifest_path = root / ".kb" / "demo-code" / "_manifest.yaml"
    manifest_path.write_text("- a\n- b\n", encoding="utf-8")

    with pytest.raises(core.CodeIngestError) as excinfo:
        _run(root)

    matches = [w for w in excinfo.value.report.warnings if "_manifest.yaml" in w]
    assert len(matches) == 1


def test_tags_curated_on_a_code_run_no_longer_bricks_the_second_run(tmp_path):
    """Controller Ruling R47c: round 4's destination check's index.yaml
    "curated"-tag signal was keyed on `d.id == doc_id` and self-defeating:
    `--tags curated` on an ordinary -code run wrote that tag onto the
    document's own index entry, so its next run found its own prior tag
    and refused itself forever, naming --doc-id/--repo-id as the culprit
    when neither was."""
    root = build_code_repo(tmp_path)
    _run(root, tags=("curated",))
    second = _run(root, tags=("curated",))
    assert second.doc_id == "demo-code"
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-code")
    assert "curated" in entry.tags


def test_curated_index_tag_on_a_different_document_does_not_block_this_run(tmp_path):
    """Over-fire re-check for Ruling R47c's drop: an index.yaml entry
    tagged "curated" for a *different*, unrelated document must not make
    this run's own -code document look curated by association."""
    root = build_code_repo(tmp_path)
    (root / ".kb").mkdir(parents=True, exist_ok=True)
    index = models.KBIndex(
        docs=[models.IndexEntry(id="unrelated-doc", title="x", tags=["code", "curated"])]
    )
    models.save_yaml_model(root / ".kb" / "index.yaml", index)

    report = _run(root)
    assert report.doc_id == "demo-code"
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()


def test_code_run_into_a_directory_with_an_unrelated_md_file_is_refused_as_foreign(tmp_path):
    """Over-fire re-check for the *curated* guard: a target directory that
    merely has a leftover, non-curated .md file in it (no banner, no
    flow./hist. manifest entries, no flows.md/history.md) must not be
    treated as *curated*. But reviewer G-1's broader foreign-destination
    guard still refuses it: with no manifest naming it, nobody can tell
    whose file NOTES.md is."""
    root = build_code_repo(tmp_path)
    doc_dir = root / ".kb" / "demo-code"
    doc_dir.mkdir(parents=True)
    (doc_dir / "NOTES.md").write_text("scratch notes, not curated\n", encoding="utf-8")

    with pytest.raises(core.CodeIngestError) as excinfo:
        _run(root)

    assert "already holds a curated document" not in str(excinfo.value)
    assert "did not generate" in str(excinfo.value)
    assert not (doc_dir / "_manifest.yaml").exists()
    assert (doc_dir / "NOTES.md").read_text(encoding="utf-8") == "scratch notes, not curated\n"


def test_repo_id_dotdot_escape_cannot_leave_kb_dir_via_scaffold_svc(tmp_path):
    """Attack beyond doc_id: --repo-id is just as user-controlled as
    --doc-id, and `scaffold_svc()` builds its own target directory from it
    with plain string interpolation (f"{repo_id}-svc") — a --repo-id
    containing ".." segments could otherwise resolve that document's
    target outside --kb-dir entirely, the same class of escape as
    test_doc_id_dotdot_escape_cannot_leave_kb_dir above but through the
    sibling code path."""
    root = build_code_repo(tmp_path)
    with pytest.raises(core.CodeIngestError, match="outside"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="../../escape", scaffold_svc=True,
        ))
    assert not (root.parent.parent / "escape-svc").exists()


def _make_dir_link(link: Path, target: Path) -> None:
    """A directory link that needs no elevated privilege on any platform
    this framework targets: a Windows *junction* (distinct from a
    symlink — `mklink /J`, no privilege required) or a POSIX symlink
    (ordinary there). Used to exercise Controller Ruling R48b, which is
    specifically about a document directory that is itself a link to
    storage elsewhere."""
    target.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=True, capture_output=True, text=True,
        )
    else:
        os.symlink(target, link, target_is_directory=True)


# ---------------------------------------------------------------------------
# Controller Ruling R48 (review round 5, re-review) — three items:
#
# R48a (CRITICAL) — dropping round 4's index "curated" tag (R47c) and
# narrowing the name check to this run's own repo_id (R47a), in the same
# round, left the "Responsibility text is human-owned" banner in
# services.md as the *only* signal protecting a freshly-scaffolded curated
# document — and that file is human-owned and human-editable. Two states
# destroy human content silently as a result: a human rewriting
# services.md without preserving the banner line, and a curated document
# whose services.md doesn't exist at all (a state this codebase explicitly
# supports and self-heals from — see test_missing_services_md_self_heals_
# from_manifest_summary above). Fixed two ways: a machine-owned manifest
# signal (title suffix / section status) that a human curating prose has
# no reason to touch, and restoring round 4's blanket reserved-suffix
# check (R48a(2), tested above as
# test_name_check_fires_for_any_repo_id_not_just_this_runs_own_slot).
#
# R48b (IMPORTANT) — containment and identity were both judged on the same
# `.resolve()`d path, which follows symlinks/junctions. A document
# directory that is itself a junction to storage elsewhere is logically
# still inside --kb-dir, but judging containment on the resolved path
# refused it outright. Fixed by splitting containment (logical path, links
# not followed) from identity (resolved path, links followed) — see
# run()'s and scaffold_svc()'s own docstring-comments.
#
# R48c (IMPORTANT) — whatever destination-check signal survives R48a must
# have an isolating test that fails when *only* that signal is removed,
# not one incidentally satisfied by a neighbouring signal (flows.md, the
# banner, ...).
# ---------------------------------------------------------------------------


def test_services_md_rewritten_without_the_banner_is_still_recognised_as_curated(tmp_path):
    """Controller Ruling R48a, state 1 (the controller's exact
    reproduction): a human rewrites services.md's prose and, in doing so,
    the banner line is gone — the manifest still holds reviewed human
    summaries. A plain -code run with a mismatched --repo-id must not
    treat this as an empty destination."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = f"Reviewed: {sec.id}"
    models.save_yaml_model(manifest_path, manifest)
    l2_path = svc_dir / "services.md"
    l2_path.write_text(
        "# demo-svc\n\n"
        "## svc.airspace-service airspace-service\n\n"
        "Owns airspace approval decisions, reviewed by the platform team.\n",
        encoding="utf-8",
    )
    original_manifest_bytes = manifest_path.read_bytes()
    original_l2_text = l2_path.read_text(encoding="utf-8")

    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc", repo_id="other",
        ))

    assert manifest_path.read_bytes() == original_manifest_bytes
    assert l2_path.read_text(encoding="utf-8") == original_l2_text


def test_missing_services_md_with_reviewed_manifest_is_still_recognised_as_curated(tmp_path):
    """Controller Ruling R48a, state 2 (the controller's exact
    reproduction): services.md doesn't exist at all — a state
    scaffold_svc() itself explicitly supports and self-heals from — while
    _manifest.yaml still holds reviewed human summaries. A plain -code
    run with a mismatched --repo-id must not treat the missing file as
    proof there is nothing to protect."""
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = f"Reviewed: {sec.id}"
    models.save_yaml_model(manifest_path, manifest)
    (svc_dir / "services.md").unlink()
    original_manifest_bytes = manifest_path.read_bytes()

    with pytest.raises(core.CodeIngestError, match="demo-svc"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-svc", repo_id="other",
        ))

    assert manifest_path.read_bytes() == original_manifest_bytes
    assert not (svc_dir / "services.md").exists()


def test_manifest_title_signal_alone_protects_a_non_svc_named_curated_dir(tmp_path):
    """Controller Ruling R48c, isolating the manifest *title* half of the
    R48a(1) signal from every neighbouring check: the target directory's
    name does not end in "-svc" (so the restored reserved-suffix check
    can't be what's refusing this), there is no services.md (so the
    banner can't be either), no flow.*/hist. section, and no flows.md/
    history.md — only the manifest's title, ending "curated service
    knowledge", and a section status of "summarized" (deliberately, so
    the *status* signal is neutralised here and this test isolates the
    title signal specifically)."""
    root = build_code_repo(tmp_path)
    curated_dir = root / ".kb" / "weird-name"
    curated_dir.mkdir(parents=True)
    manifest = models.Manifest(
        id="weird-name",
        title="demo — curated service knowledge",
        sections=[
            models.SectionEntry(
                id="svc.airspace-service", title="airspace-service",
                summary="Owns airspace approval decisions.",
                status="summarized", file="services",
            ),
        ],
    )
    models.save_yaml_model(curated_dir / "_manifest.yaml", manifest)
    original_manifest_bytes = (curated_dir / "_manifest.yaml").read_bytes()

    with pytest.raises(core.CodeIngestError, match="weird-name"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="weird-name", repo_id="demo",
        ))

    assert (curated_dir / "_manifest.yaml").read_bytes() == original_manifest_bytes


def test_manifest_status_signal_alone_protects_a_non_svc_named_curated_dir(tmp_path):
    """Controller Ruling R48c, isolating the manifest *status* half of the
    R48a(1) signal: same setup as the title-isolating test above, but the
    title deliberately does NOT end "curated service knowledge" (so the
    title signal is neutralised) while a section carries status
    "reviewed" — a status run() itself never writes for a -code
    document's sections.

    `manifest.id` is deliberately "elsewhere-doc", NOT "weird-name" (the
    doc_id this run targets): Controller Ruling R49(1), added at Task
    B10, gates this signal on `manifest.id != doc_id` to stop it firing
    on a document's own prior run (see the regression tests below), so
    an isolating test for the status signal must now use a manifest that
    is genuinely foreign to this run's doc_id, exactly as `demo-svc` is
    foreign to a `demo-code` run in the ruling's own example."""
    root = build_code_repo(tmp_path)
    curated_dir = root / ".kb" / "weird-name"
    curated_dir.mkdir(parents=True)
    manifest = models.Manifest(
        id="elsewhere-doc",
        title="an unrelated title",
        sections=[
            models.SectionEntry(
                id="svc.airspace-service", title="airspace-service",
                summary="Owns airspace approval decisions.",
                status="reviewed", file="services",
            ),
        ],
    )
    models.save_yaml_model(curated_dir / "_manifest.yaml", manifest)
    original_manifest_bytes = (curated_dir / "_manifest.yaml").read_bytes()

    with pytest.raises(core.CodeIngestError, match="weird-name"):
        core.run(core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="weird-name", repo_id="demo",
        ))

    assert (curated_dir / "_manifest.yaml").read_bytes() == original_manifest_bytes


# ---------------------------------------------------------------------------
# Controller Ruling R49(1), Task B10 — the `-code` self-lockout regression.
# Two ordinary sibling commands write exactly the "pending"/"reviewed"
# statuses the destination check watches for onto a `-code` document's own
# manifest: `kb summarize --redo` with no DOC_ID, and `kb approve
# --all-changed` with no DOC_ID. Verified as a regression: at the commit
# before this fix, either command locked `demo-code` out of its own next
# `code-ingest` run forever, blaming --doc-id/--repo-id (neither is the
# cause) and suggesting a remedy (pick a different --doc-id) that would
# have created a duplicate document instead of repairing anything.
# ---------------------------------------------------------------------------


def test_summarize_redo_with_no_doc_id_does_not_lock_code_ingest_out_of_itself(
    tmp_path,
):
    from center_kb.summarize import plan_redo, redo_reset

    root = build_code_repo(tmp_path)
    _run(root)
    manifest_path = root / ".kb" / "demo-code" / "_manifest.yaml"
    before = models.load_yaml_model(manifest_path, models.Manifest)
    assert all(s.status == "summarized" for s in before.sections)

    redo_reset(root / ".kb", plan_redo(root / ".kb", None))  # --all: every doc, including demo-code
    after_redo = models.load_yaml_model(manifest_path, models.Manifest)
    assert all(s.status == "pending" for s in after_redo.sections)

    # Must NOT raise CodeIngestError — this is demo-code re-ingesting
    # itself, not a foreign document landing on a curated destination.
    _run(root)
    after_reingest = models.load_yaml_model(manifest_path, models.Manifest)
    assert all(s.status == "summarized" for s in after_reingest.sections)


def test_approve_all_changed_with_no_doc_id_does_not_lock_code_ingest_out_of_itself(
    tmp_path, run_git
):
    from center_kb.review import approve_all_changed

    root = build_code_repo(tmp_path)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "c0 - pre code-ingest")
    rev0 = run_git(root, "rev-parse", "HEAD")

    _run(root)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "c1 - code-ingest")

    reports = approve_all_changed(root / ".kb", rev0, by="sme <sme@x>")  # no doc_id -> every doc
    assert any(r.doc_id == "demo-code" and r.flipped for r in reports)
    manifest_path = root / ".kb" / "demo-code" / "_manifest.yaml"
    after_approve = models.load_yaml_model(manifest_path, models.Manifest)
    assert all(s.status == "reviewed" for s in after_approve.sections)

    # Must NOT raise CodeIngestError — same document, not a foreign one.
    _run(root)
    after_reingest = models.load_yaml_model(manifest_path, models.Manifest)
    assert all(s.status == "summarized" for s in after_reingest.sections)


def test_foreign_curated_manifest_with_mismatched_id_still_refuses(tmp_path):
    """The other half of Ruling R49(1): the identity gate must not turn
    into a blanket bypass. A manifest that genuinely belongs to a
    different document (`manifest.id != doc_id`) still refuses via the
    status signal alone — title does not end "curated service
    knowledge", no flow./hist. section, no services.md/flows.md/
    history.md on disk."""
    root = build_code_repo(tmp_path)
    doc_dir = root / ".kb" / "demo-code"
    doc_dir.mkdir(parents=True)
    foreign = models.Manifest(
        id="demo-svc",
        title="an unrelated title",
        sections=[
            models.SectionEntry(
                id="svc.airspace-service", title="airspace-service",
                summary="Owns airspace approval decisions.",
                status="reviewed", file="services",
            ),
        ],
    )
    models.save_yaml_model(doc_dir / "_manifest.yaml", foreign)
    original_manifest_bytes = (doc_dir / "_manifest.yaml").read_bytes()

    with pytest.raises(core.CodeIngestError, match="demo-code"):
        _run(root)

    assert (doc_dir / "_manifest.yaml").read_bytes() == original_manifest_bytes


def test_scaffold_svc_into_a_junctioned_directory_does_not_refuse(tmp_path):
    """Controller Ruling R48b, over-fire re-check: a curated document
    directory that is itself a link to storage elsewhere must not lock
    out the command whose job is to maintain it. Judging containment on
    the *resolved* (link-following) path — this guard's own first
    attempt at R47(a) — refused this outright, naming --repo-id as the
    cause when it was not."""
    root = build_code_repo(tmp_path)
    external = tmp_path / "external-storage"
    kb_dir = root / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    _make_dir_link(kb_dir / "demo-svc", external)

    report = core.run(core.CodeIngestOptions(
        repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo",
        scaffold_svc=True,
    ))

    assert report.doc_id == "demo-code"
    # Written through the link, at the real target — not merely "did not
    # raise": the curated document actually landed where the link points.
    assert (external / "_manifest.yaml").is_file()
    assert (external / "services.md").is_file()


def test_code_run_into_a_junctioned_ordinary_directory_does_not_refuse(tmp_path):
    """Controller Ruling R48b, the symmetric case in run()'s own guard
    (not just scaffold_svc()'s): an ordinary, uncurated -code document
    directory that happens to be a link must not be refused for escaping
    --kb-dir either."""
    root = build_code_repo(tmp_path)
    external = tmp_path / "external-storage"
    kb_dir = root / ".kb"
    kb_dir.mkdir(parents=True, exist_ok=True)
    _make_dir_link(kb_dir / "demo-code", external)

    report = _run(root)

    assert report.doc_id == "demo-code"
    assert (external / "_manifest.yaml").is_file()
