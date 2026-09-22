"""Engine tests for `kb ticket check` (`ticketcheck.check`).

Hermetic: the -code document is a REAL `demo-code` produced by
`codeingest.core.run()` over `tests/fixtures_coderepo.build_code_repo`, so
every id, column, route, command and tree path asserted here is what the
extractors actually emit (see the spec's §1 table). No hub, no network.
"""

from __future__ import annotations

from pathlib import Path

from strata_kb import models, ticketcheck
from strata_kb.codeingest import core
from strata_kb.lintcore import LintReport
from tests.fixtures_coderepo import build_code_repo

# `code_doc` ((kb_dir, revision) for a freshly ingested `demo-code`) lives in
# tests/conftest.py -- shared with test_cli_ticket_check.py, which needs the
# identical fixture. `models`/`core`/`build_code_repo` stay imported here for
# test_path_after_the_line_cap_marker_is_a_warning, which builds its own
# oversized repo directly rather than through the fixture.

DEFAULTS = {
    "Grounded on": "demo:demo-code @ {rev}",
    "Service": "svc.airspace-service",
    "Files": ["src/airspace/service.py"],
    "Tables": "db.restrictive_airspace.designation",
    "Routes": "api.airspace — GET /airspace",
    "Externals": "int.kafka",
    "Verify with": "cmd.test — `pytest -q --cov=airspace`",
    "Open decisions": ["none"],
}


def grounding(rev: str, **overrides) -> str:
    """The `## Technical grounding` body, template order, with overrides.
    A list value renders as sub-bullets; `None` drops the field."""
    fields = {**DEFAULTS, **overrides}
    out: list[str] = []
    for name, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            out.append(f"- {name}:")
            out.extend(f"  - {item}" for item in value)
        else:
            out.append(f"- {name}: {str(value).format(rev=rev)}")
    return "\n".join(out)


MISSION = """# Billing — mission
> Mission: M-demo

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.billing — charges per flight plan | DECIDED | tech-lead | M-demo-US1 |
| D2 | New db.invoice table | OPEN | Alice | M-demo-US1 |
"""


def decisions_of(mission_text: str | None):
    """A `load_decisions` over one in-memory mission; `None` = file missing."""
    def load(mission_id: str):
        if mission_text is None:
            return None
        return ticketcheck.parse_decisions(mission_text, f"missions/{mission_id}.md")
    return load


def ticket(section: str | None, *, parent: str | None = None, heading: str = "## Technical grounding") -> str:
    parts = ["# T-1 — Show airspace"]
    if parent is not None:
        parts.append(f"> Parent mission: {parent}")
    parts += ["", "## Summary", "Something.", ""]
    if section is not None:
        parts += [heading, section, ""]
    parts += ["## Open questions", "- [ ] none", ""]
    return "\n".join(parts)


def run(text: str, kb_dir: Path, *, heading: str = "## Technical grounding", load_decisions=None) -> LintReport:
    def load_doc(repo, doc):
        d = kb_dir / doc
        if not (d / "_manifest.yaml").exists():
            return None
        return ticketcheck.load_doc_dir(d, str(d))

    return ticketcheck.check(text, load_doc=load_doc, heading=heading, load_decisions=load_decisions)


def errors(r: LintReport) -> list[str]:
    return [i.message for i in r.issues if i.level == "error"]


def warnings(r: LintReport) -> list[str]:
    return [i.message for i in r.issues if i.level == "warning"]


def notes(r: LintReport) -> list[str]:
    return list(r.notes)


# --- Task 1: section, Grounded on, load, revision -------------------------


def test_golden_section_passes(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev)), kb_dir)
    assert errors(report) == [], report.render("Grounding")
    assert report.passed is True
    assert any("demo-code read from" in n for n in notes(report))


def test_missing_section_is_an_error(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(None), kb_dir)
    assert report.passed is False
    assert errors(report) == ["missing '## Technical grounding' — run /sa-ticket-ground"]


def test_missing_grounded_on_stops_with_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Grounded on": None})), kb_dir)
    assert report.passed is False
    assert len(errors(report)) == 1
    assert "Grounded on:" in errors(report)[0]


def test_malformed_grounded_on_names_the_expected_shape(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(grounding("x", **{"Grounded on": "demo-code (rev abc1234)"})), kb_dir)
    assert len(errors(report)) == 1
    assert "<repo-id>:<doc-id> @ <revision>" in errors(report)[0]
    assert "(line 7)" in errors(report)[0]


def test_unknown_document_is_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Grounded on": "other:other-code @ {rev}"})), kb_dir)
    assert len(errors(report)) == 1
    assert "other-code" in errors(report)[0]
    assert "not found" in errors(report)[0]
    assert "(line 7)" in errors(report)[0]


def test_unreadable_manifest_is_an_error_not_a_traceback(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "_manifest.yaml").write_text("id: [broken", encoding="utf-8")
    report = run(ticket(grounding(rev)), kb_dir)
    assert len(errors(report)) == 1
    assert "could not read" in errors(report)[0]
    assert "_manifest.yaml" in errors(report)[0]


def test_revision_mismatch_is_stale_grounding(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(grounding("deadbee")), kb_dir)
    assert any("stale grounding" in e and "deadbee" in e for e in errors(report))
    assert any("stale grounding" in e and "(line 7)" in e for e in errors(report))


def test_long_revision_prefix_matches(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev + "0" * (40 - len(rev)))), kb_dir)
    assert not any("stale grounding" in e for e in errors(report))
    assert errors(report) == [], report.render("Grounding")


def test_empty_manifest_revision_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    path = kb_dir / "demo-code" / "_manifest.yaml"
    m = models.load_yaml_model(path, models.Manifest)
    m.revision = ""
    models.save_yaml_model(path, m)
    report = run(ticket(grounding(rev)), kb_dir)
    assert not any("stale grounding" in e for e in errors(report))
    assert any("no revision" in w for w in warnings(report))


def test_render_label_defaults_to_dor_and_accepts_grounding():
    r = LintReport(issues=[])
    assert r.render().endswith("DoR: PASS")
    assert r.render("Grounding").endswith("Grounding: PASS")


# --- Task 2: ids, [NEW], Service, Open decisions ---------------------------


def test_unknown_ids_are_errors_with_line_numbers(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(
        rev,
        Service="svc.nope",
        Tables="db.ghost.col",
        Routes="api.missing",
        Externals="int.unknown",
    ))
    report = run(text, kb_dir)
    msgs = errors(report)
    for bad, line in (("svc.nope", 8), ("db.ghost", 11), ("api.missing", 12), ("int.unknown", 13)):
        assert any(f"unknown id '{bad}'" in m and f"(line {line})" in m for m in msgs), (bad, msgs)


def test_new_marker_exempts_the_line_and_emits_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives with this ticket]"))
    report = run(text, kb_dir)
    assert not any("int.stripe" in e for e in errors(report))
    assert any("new: int.stripe — billing arrives with this ticket" in n for n in notes(report))


def test_new_marker_without_a_reason_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Externals="int.stripe [NEW]")), kb_dir)
    assert not any("int.stripe" in e for e in errors(report))
    assert any("[NEW] without a reason" in w for w in warnings(report))


def test_ids_inside_file_paths_are_not_scanned(code_doc):
    # `src/api.py` must not be read as the id `api.py`.
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/api.py [NEW: new module]"])), kb_dir)
    assert not any("api.py" in e for e in errors(report))
    # If `Files:` lines were id-scanned, the [NEW] branch would suppress
    # the error but still emit a note — assert that path never fires.
    assert not any("new: api.py" in n for n in notes(report))


def test_missing_service_line_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Service="none")), kb_dir)
    assert any("no `svc.<name>`" in w for w in warnings(report))


def test_open_decisions_fail_the_gate_one_error_each_plus_summary(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, **{"Open decisions": [
        "Failure mode: what if Kafka is down during approval?",
        "Request body of POST /airspace",
    ]}))
    report = run(text, kb_dir)
    assert report.passed is False
    msgs = errors(report)
    assert any("open decision: Failure mode: what if Kafka is down" in m and "(line 16)" in m for m in msgs)
    assert any("open decision: Request body of POST /airspace" in m and "(line 17)" in m for m in msgs)
    assert "2 open decision(s) — resolve before Dev" in msgs


def test_open_decisions_none_variants_pass(code_doc):
    kb_dir, rev = code_doc
    for word in ("none", "None", "N/A", "n/a"):
        report = run(ticket(grounding(rev, **{"Open decisions": [word]})), kb_dir)
        assert not any("open decision" in e for e in errors(report)), word


def test_inline_open_decision_counts_too(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Open decisions": "retry policy unknown"})), kb_dir)
    assert any("open decision: retry policy unknown" in e for e in errors(report))


def test_blank_line_between_open_decisions_does_not_crash(code_doc):
    kb_dir, rev = code_doc
    section = grounding(rev, **{"Open decisions": ["first?", "second?"]})
    section = section.replace("  - first?\n", "  - first?\n\n")
    section += "\n"  # extra trailing blank line inside the section
    report = run(ticket(section), kb_dir)
    msgs = errors(report)
    assert any("open decision: first?" in m for m in msgs)
    assert any("open decision: second?" in m for m in msgs)


def test_new_marker_on_a_column_of_a_known_table_emits_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(
        rev,
        Tables="db.restrictive_airspace.brand_new [NEW: column arrives with this ticket]",
    ))
    report = run(text, kb_dir)
    assert any(
        "new: db.restrictive_airspace.brand_new — column arrives with this ticket" in n
        for n in notes(report)
    )
    assert not any("db.restrictive_airspace.brand_new" in e for e in errors(report))


# --- Task 3: columns, routes, commands -------------------------------------


def test_unknown_column_is_an_error_known_column_is_fine(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Tables="db.restrictive_airspace.nope")), kb_dir)
    assert any("column 'nope'" in e and "db.restrictive_airspace" in e and "(line 11)" in e for e in errors(bad))
    good = run(ticket(grounding(rev, Tables="db.restrictive_airspace.effective_date")), kb_dir)
    assert not any("column" in e for e in errors(good))


def test_route_must_be_a_row_of_the_tag_table(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Routes="api.airspace — DELETE /airspace")), kb_dir)
    assert any("route 'DELETE /airspace'" in e and "api.airspace" in e and "(line 12)" in e for e in errors(bad))
    good = run(ticket(grounding(rev, Routes="api.airspace — POST /airspace")), kb_dir)
    assert not any("route" in e for e in errors(good))


def test_backticked_route_is_accepted(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Routes="api.airspace — `GET /airspace`")), kb_dir)
    assert not any("route" in e for e in errors(report))


def test_tag_without_a_route_pair_is_accepted(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Routes="api.airspace")), kb_dir)
    assert not any("route" in e for e in errors(report))


def test_command_must_be_primary_or_an_alternative_verbatim(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest -q`"})), kb_dir)
    assert any("command not in cmd.test" in e and "(line 14)" in e for e in errors(bad))
    alt = run(ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest`"})), kb_dir)
    assert not any("command" in e for e in errors(alt))
    other = run(ticket(grounding(rev, **{"Verify with": "cmd.lint — `ruff check src`"})), kb_dir)
    assert not any("command" in e for e in errors(other))


def test_command_line_without_a_code_span_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Verify with": "cmd.test"})), kb_dir)
    assert any("cmd.test" in w and "backticks" in w for w in warnings(report))


def test_unreadable_group_file_degrades_to_a_warning(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "db.md").write_bytes(b"\xff\xfe\x00\xd8")
    report = run(ticket(grounding(rev, Tables="db.restrictive_airspace.nope")), kb_dir)
    assert not any("column" in e for e in errors(report))
    assert any("db.md" in w and "skipped" in w for w in warnings(report))


# --- Task 3 fix round: any code span, route punctuation, missing heading ---


def test_command_check_accepts_any_code_span_on_the_line(code_doc):
    kb_dir, rev = code_doc
    good = run(ticket(grounding(rev, **{"Verify with": "`cmd.test` — `pytest`"})), kb_dir)
    assert not any("command" in e for e in errors(good))
    bad = run(ticket(grounding(rev, **{"Verify with": "`cmd.test` — `nope`"})), kb_dir)
    msgs = errors(bad)
    assert any("command not in cmd.test" in m and "found:" in m and "`nope`" in m for m in msgs)


def test_route_trailing_punctuation_is_tolerated(code_doc):
    kb_dir, rev = code_doc
    good = run(ticket(grounding(rev, Routes="api.airspace — GET /airspace, POST /airspace.")), kb_dir)
    assert not any("route" in e for e in errors(good))
    bad = run(ticket(grounding(rev, Routes="api.airspace — DELETE /airspace")), kb_dir)
    assert any("route 'DELETE /airspace'" in e and "GET /airspace" in e for e in errors(bad))


def test_missing_l2_heading_is_a_warning_not_a_silent_pass(code_doc):
    kb_dir, rev = code_doc
    db_md = kb_dir / "demo-code" / "db.md"
    db_md.write_text(
        db_md.read_text(encoding="utf-8").replace(
            "## db.restrictive_airspace", "## db.renamed"
        ),
        encoding="utf-8",
    )
    report = run(ticket(grounding(rev, Tables="db.restrictive_airspace.nope")), kb_dir)
    assert not any("column" in e for e in errors(report))
    assert any("db.restrictive_airspace" in w and "skipped" in w for w in warnings(report))


# --- Task 4: Files vs struct.tree -------------------------------------------


def test_files_present_missing_and_new(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Files=[
        "src/airspace/service.py",
        "db/migration/V1__create_airspace.sql",
        "src/airspace/ghost.py",
        "src/airspace/approval.py [NEW: created by this ticket]",
    ]))
    report = run(text, kb_dir)
    msgs = errors(report)
    assert any("file 'src/airspace/ghost.py' not in struct.tree" in m and "(line 12)" in m for m in msgs)
    assert not any("service.py" in m or "V1__create" in m for m in msgs)
    assert any("new: src/airspace/approval.py — created by this ticket" in n for n in notes(report))


def test_inline_files_value_is_verified(code_doc):
    # `grounding()` only ever renders `Files` as sub-bullets — an inline
    # `- Files: <path>` value has to be built by hand.
    kb_dir, rev = code_doc
    bad = grounding(rev, Files=None).replace(
        "- Tables:", "- Files: src/airspace/ghost.py\n- Tables:"
    )
    report = run(ticket(bad), kb_dir)
    msgs = errors(report)
    assert any(
        "file 'src/airspace/ghost.py' not in struct.tree" in m and "(line 9)" in m
        for m in msgs
    )

    good = grounding(rev, Files=None).replace(
        "- Tables:", "- Files: src/airspace/service.py\n- Tables:"
    )
    report = run(ticket(good), kb_dir)
    assert not any("file" in e for e in errors(report))


def test_directory_entries_count_as_paths(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/airspace", "db/migration/"])), kb_dir)
    assert not any("not in struct.tree" in e for e in errors(report))


def test_path_beyond_depth_cap_is_a_warning_not_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/airspace/deep/deeper/x.py"])), kb_dir)
    assert not any("not in struct.tree" in e for e in errors(report))
    assert any("cannot verify 'src/airspace/deep/deeper/x.py'" in w and "depth" in w for w in warnings(report))


def test_path_after_the_line_cap_marker_is_a_warning(tmp_path: Path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    wide = root / "wide"
    wide.mkdir()
    for n in range(700):  # 700 files > _L3_MAX_LINES=600 → the tree is capped
        (wide / f"f{n:04d}.txt").write_text("x", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    kb_dir = tmp_path / "kb"
    core.run(core.CodeIngestOptions(repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"))
    rev = models.load_yaml_model(kb_dir / "demo-code" / "_manifest.yaml", models.Manifest).revision
    raw = (kb_dir / "demo-code" / "structure.raw.md").read_text(encoding="utf-8")
    assert "more entries omitted" in raw  # precondition: the cap fired
    report = run(ticket(grounding(rev, Files=["wide/f0699.txt", "wide/f0000.txt", "aaa.txt"])), kb_dir)
    # The listing is truncated, so an absent path can never be proven absent:
    # f0699 (past the cut) and aaa.txt (would sort before it, but the marker
    # names a bare file name, so order is not comparable) are both warnings;
    # f0000 is listed → ok. No false errors on a capped tree.
    assert any("cannot verify 'wide/f0699.txt'" in w and "line cap" in w for w in warnings(report))
    assert any("cannot verify 'aaa.txt'" in w and "line cap" in w for w in warnings(report))
    assert not any("f0000" in e for e in errors(report))
    assert not any("not in struct.tree" in e for e in errors(report))


def test_missing_structure_raw_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "structure.raw.md").unlink()
    report = run(ticket(grounding(rev)), kb_dir)
    assert not any("struct.tree" in e for e in errors(report))
    assert any("structure.raw.md" in w and "file checks skipped" in w for w in warnings(report))


# --- Task 1 (greenfield): [NEW: D<n>] against the parent mission ----------


def test_parse_decisions_reads_id_status_owner_by_header_name():
    table = ticketcheck.parse_decisions(MISSION, "missions/M-demo.md")
    assert table.source == "missions/M-demo.md"
    assert table.rows["D1"] == ticketcheck.Decision("D1", "DECIDED", "tech-lead")
    assert table.rows["D2"].status == "OPEN"


def test_parse_decisions_survives_a_reordered_table():
    text = (
        "## Technology decisions\n"
        "| Status | Owner | # | Decision |\n"
        "|---|---|---|---|\n"
        "| decided | Bob | D7 | whatever |\n"
    )
    table = ticketcheck.parse_decisions(text, "x")
    assert table.rows == {"D7": ticketcheck.Decision("D7", "decided", "Bob")}


def test_parse_decisions_without_the_section_is_empty():
    assert ticketcheck.parse_decisions("# nothing here\n", "x").rows == {}


def test_decided_reference_passes_with_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Service="svc.billing [NEW: D1]", Files=["src/billing/ [NEW: D1]"]),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert errors(report) == [], report.render("Grounding")
    assert any("new: svc.billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report))
    assert any("new: src/billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report))


def test_open_decision_reference_is_an_error_naming_the_owner(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Tables="db.invoice [NEW: D2]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert report.passed is False
    assert any("decision D2 is OPEN (owner: Alice)" in e for e in errors(report))


def test_missing_decision_row_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D9]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any("decision D9 not in missions/M-demo.md's Technology decisions" in e for e in errors(report))


def test_decision_reference_without_a_parent_mission_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"))
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any("[NEW: D1] needs a parent mission" in e for e in errors(report))
    # Externals is the 8th grounding line; the section heading sits on line 6.
    assert "(line 13)" in [e for e in errors(report) if "D1" in e][0]


def test_decision_reference_with_a_missing_mission_file_is_an_error(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"), parent="M-gone")
    report = run(text, kb_dir, load_decisions=decisions_of(None))
    assert any("parent mission 'M-gone' not found" in e for e in errors(report))


def test_decision_reference_with_no_loader_is_treated_as_not_found(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"), parent="M-demo")
    report = run(text, kb_dir)  # load_decisions=None: caller supplied no missions dir
    assert any("parent mission 'M-demo' not found" in e for e in errors(report))


def test_free_text_new_with_a_decisions_table_present_warns(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives later]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert report.passed is True
    assert any("reference the row as [NEW: D<n>]" in w for w in warnings(report))


def test_free_text_new_without_a_parent_mission_stays_a_plain_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives later]"))
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("[NEW: D<n>]" in w for w in warnings(report))
    assert any("new: int.stripe — billing arrives later" in n for n in notes(report))
