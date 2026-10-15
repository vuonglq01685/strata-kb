"""Engine tests for `kb ticket check` (`ticketcheck.check`).

Hermetic: the -code document is a REAL `demo-code` produced by
`codeingest.core.run()` over `tests/fixtures_coderepo.build_code_repo`, so
every id, column, route, command and tree path asserted here is what the
extractors actually emit (see the spec's §1 table). No hub, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import gitio, models, ticketcheck
from strata_kb.codeingest import core
from strata_kb.errors import KbError
from strata_kb.kbcontext import KBRef
from strata_kb.lintcore import LintReport
from strata_kb.mdutils import slice_section
from strata_kb.resolve import ResolvedRef
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
    "Volumes": "svc.airspace-service — none",
    "Healthchecks": "svc.airspace-service — `curl -f http://localhost:8080/health`",
    "Devices": "svc.airspace-service — nvidia:gpu",
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


def ticket(
    section: str | None,
    *,
    parent: str | None = None,
    heading: str = "## Technical grounding",
) -> str:
    parts = ["# T-1 — Show airspace"]
    if parent is not None:
        parts.append(f"> Parent mission: {parent}")
    parts += ["", "## Summary", "Something.", ""]
    if section is not None:
        parts += [heading, section, ""]
    parts += ["## Open questions", "- [ ] none", ""]
    return "\n".join(parts)


def run(
    text: str,
    kb_dir: Path,
    *,
    heading: str = "## Technical grounding",
    load_decisions=None,
    load_drift=None,
) -> LintReport:
    def load_doc(repo, doc):
        d = kb_dir / doc
        if not (d / "_manifest.yaml").exists():
            return None
        return ticketcheck.load_doc_dir(d, str(d))

    return ticketcheck.check(
        text,
        load_doc=load_doc,
        heading=heading,
        load_decisions=load_decisions,
        load_drift=load_drift,
    )


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
    assert errors(report) == [
        "missing '## Technical grounding' — run /sa-ticket-ground"
    ]


def test_missing_grounded_on_stops_with_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Grounded on": None})), kb_dir)
    assert report.passed is False
    assert len(errors(report)) == 1
    assert "Grounded on:" in errors(report)[0]


def test_malformed_grounded_on_names_the_expected_shape(code_doc):
    kb_dir, _ = code_doc
    report = run(
        ticket(grounding("x", **{"Grounded on": "demo-code (rev abc1234)"})), kb_dir
    )
    assert len(errors(report)) == 1
    assert "<repo-id>:<doc-id> @ <revision>" in errors(report)[0]
    assert "(line 7)" in errors(report)[0]


def test_unknown_document_is_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, **{"Grounded on": "other:other-code @ {rev}"})), kb_dir
    )
    assert len(errors(report)) == 1
    assert "other-code" in errors(report)[0]
    assert "not found" in errors(report)[0]
    assert "(line 7)" in errors(report)[0]


def test_unreadable_manifest_is_an_error_not_a_traceback(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "_manifest.yaml").write_text(
        "id: [broken", encoding="utf-8"
    )
    report = run(ticket(grounding(rev)), kb_dir)
    assert len(errors(report)) == 1
    assert "could not read" in errors(report)[0]
    assert "_manifest.yaml" in errors(report)[0]


NO_BASELINE_DEADBEE = (
    "grounded @deadbee, now @{rev} — no baseline to diff, cited facts still hold"
)
UNCHANGED_DEADBEE = (
    "grounded @deadbee, still valid at @{rev} — cited sections unchanged"
)


def tier2(old: str, new: str) -> str:
    return (
        f"grounding drifted since @{old} (now @{new}) and no longer holds "
        "— re-run /sa-ticket-ground"
    )


def test_revision_mismatch_alone_passes(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding("deadbee")), kb_dir)
    assert errors(report) == [], report.render("Grounding")
    assert NO_BASELINE_DEADBEE.format(rev=rev) in warnings(report)
    assert not any("stale grounding" in e for e in errors(report))


def test_revision_mismatch_with_unknown_id_is_tier2(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding("deadbee", Service="svc.gone")), kb_dir)
    assert any("unknown id 'svc.gone'" in e for e in errors(report))
    assert tier2("deadbee", rev) in errors(report)


def test_revision_mismatch_with_dropped_column_is_tier2(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding("deadbee", Tables="db.restrictive_airspace.no_such_col"))
    report = run(text, kb_dir)
    assert any("no_such_col" in e for e in errors(report))
    assert tier2("deadbee", rev) in errors(report)


def test_open_decision_with_moved_revision_has_no_reground_line(code_doc):
    kb_dir, _ = code_doc
    report = run(
        ticket(grounding("deadbee", **{"Open decisions": ["pick a queue"]})), kb_dir
    )
    assert any("open decision" in e for e in errors(report))
    assert not any("grounding drifted" in e for e in errors(report))


def test_load_drift_used_on_mismatch(code_doc):
    kb_dir, rev = code_doc
    seen: list[tuple] = []

    def load_drift(repo, doc_id, old_rev):
        seen.append((repo, doc_id, old_rev))
        return [
            ResolvedRef(
                ref=KBRef(
                    repo_id="demo",
                    doc_id="demo-code",
                    section_id="svc.airspace-service",
                ),
                status="ok",
                citation="demo-code §svc.airspace-service",
                content="",
                tokens=0,
            )
        ]

    report = run(ticket(grounding("deadbee")), kb_dir, load_drift=load_drift)
    assert seen == [("demo", "demo-code", "deadbee")]
    assert UNCHANGED_DEADBEE.format(rev=rev) in report.notes
    assert errors(report) == []


def _drift_ref(sid: str, status: str, content: str = "") -> ResolvedRef:
    return ResolvedRef(
        ref=KBRef(repo_id="demo", doc_id="demo-code", section_id=sid),
        status=status,  # type: ignore[arg-type]
        citation=f"demo-code §{sid}",
        content=content,
        tokens=0,
    )


def _current_section(kb_dir: Path, sid: str) -> str:
    m = models.load_yaml_model(kb_dir / "demo-code" / "_manifest.yaml", models.Manifest)
    group = next(s.file for s in m.sections if s.id == sid)
    text = (kb_dir / "demo-code" / f"{group}.md").read_text(encoding="utf-8")
    body = slice_section(text, sid)
    assert body
    return body


def test_stale_cited_section_warns_with_the_current_text_in_the_diff(code_doc):
    kb_dir, rev = code_doc
    sid = "svc.airspace-service"
    current = _current_section(kb_dir, sid)
    report = run(
        ticket(grounding("deadbee")),
        kb_dir,
        load_drift=lambda *a: [_drift_ref(sid, "stale", "OLD BASELINE TEXT\n")],
    )
    assert errors(report) == []
    (warn,) = [w for w in warnings(report) if w.startswith("grounded @deadbee")]
    assert f"§{sid} changed" in warn
    assert f"demo-code §{sid} @deadbee" in warn
    assert "-OLD BASELINE TEXT" in warn
    assert "+" + current.strip().splitlines()[0] in warn


def test_skipped_compose_checks_with_moved_revision_are_unverified(code_doc):
    kb_dir, rev = code_doc
    services_md = kb_dir / "demo-code" / "services.md"
    text = services_md.read_text(encoding="utf-8")
    text = "\n".join(
        ln
        for ln in text.splitlines()
        if not ln.startswith(("| Volumes |", "| Healthcheck |", "| Devices |"))
    )
    services_md.write_text(text + "\n", encoding="utf-8")
    report = run(
        ticket(grounding("deadbee")),
        kb_dir,
        load_drift=lambda *a: [_drift_ref("svc.airspace-service", "ok")],
    )
    assert errors(report) == []
    assert (
        f"grounded @deadbee, still valid at @{rev}"
        " — cited facts that could be checked still hold"
    ) in notes(report)
    assert (
        "some cited facts could not be verified since @deadbee (see warnings above)"
        " — check them by hand"
    ) in warnings(report)


def test_dropped_compose_lines_with_moved_revision_are_unverified(code_doc):
    kb_dir, _ = code_doc
    text = ticket(grounding("deadbee", Volumes=None, Healthchecks=None, Devices=None))
    report = run(
        text,
        kb_dir,
        load_drift=lambda *a: [_drift_ref("svc.airspace-service", "ok")],
    )
    assert errors(report) == []
    assert any("could not be verified since @deadbee" in w for w in warnings(report))


def test_plain_warning_with_moved_revision_is_not_unverified(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(
            grounding(
                "deadbee",
                Service="none",
                Volumes="none",
                Healthchecks="none",
                Devices="none",
            )
        ),
        kb_dir,
        load_drift=lambda *a: [_drift_ref("svc.airspace-service", "ok")],
    )
    assert any("no `svc.<name>`" in w for w in warnings(report))
    assert UNCHANGED_DEADBEE.format(rev=rev) in notes(report)
    assert not any("could not be verified" in w for w in warnings(report))


def test_load_drift_error_degrades(code_doc):
    kb_dir, rev = code_doc

    def load_drift(repo, doc_id, old_rev):
        raise gitio.GitError("boom")

    report = run(ticket(grounding("deadbee")), kb_dir, load_drift=load_drift)
    assert report.passed
    assert NO_BASELINE_DEADBEE.format(rev=rev) in warnings(report)


def test_load_drift_non_kb_errors_degrade(code_doc):
    """drift_refs can raise past KbError (undecodable L2, a path outside the
    checkout): still the no-baseline warning, never a traceback."""
    kb_dir, rev = code_doc
    for exc in (
        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"),
        OSError("disk gone"),
        ValueError("not relative"),
    ):

        def load_drift(repo, doc_id, old_rev, exc=exc):
            raise exc

        report = run(ticket(grounding("deadbee")), kb_dir, load_drift=load_drift)
        assert report.passed, exc
        assert NO_BASELINE_DEADBEE.format(rev=rev) in warnings(report), exc


def test_open_decision_new_marker_with_moved_revision_is_not_drift(code_doc):
    kb_dir, _ = code_doc
    text = ticket(grounding("deadbee", Tables="db.invoice [NEW: D2]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any(i.code == ticketcheck.DECISION for i in report.issues)
    assert not any("grounding drifted" in e for e in errors(report))


def test_matching_revision_unchanged(code_doc):
    kb_dir, rev = code_doc
    called: list[object] = []
    report = run(ticket(grounding(rev)), kb_dir, load_drift=lambda *a: called.append(a))
    assert errors(report) == []
    assert called == []
    assert not any(n.startswith("grounded @") for n in report.notes)
    assert not any(w.startswith("grounded @") for w in warnings(report))


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
    text = ticket(
        grounding(
            rev,
            Service="svc.nope",
            Tables="db.ghost.col",
            Routes="api.missing",
            Externals="int.unknown",
        )
    )
    report = run(text, kb_dir)
    msgs = errors(report)
    for bad, line in (
        ("svc.nope", 8),
        ("db.ghost", 11),
        ("api.missing", 12),
        ("int.unknown", 13),
    ):
        assert any(
            f"unknown id '{bad}'" in m and f"(line {line})" in m for m in msgs
        ), (bad, msgs)


def test_new_marker_exempts_the_line_and_emits_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Externals="int.stripe [NEW: billing arrives with this ticket]")
    )
    report = run(text, kb_dir)
    assert not any("int.stripe" in e for e in errors(report))
    assert any(
        "new: int.stripe — billing arrives with this ticket" in n for n in notes(report)
    )


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
    text = ticket(
        grounding(
            rev,
            **{
                "Open decisions": [
                    "Failure mode: what if Kafka is down during approval?",
                    "Request body of POST /airspace",
                ]
            },
        )
    )
    report = run(text, kb_dir)
    assert report.passed is False
    msgs = errors(report)
    assert any(
        "open decision: Failure mode: what if Kafka is down" in m and "(line 16)" in m
        for m in msgs
    )
    assert any(
        "open decision: Request body of POST /airspace" in m and "(line 17)" in m
        for m in msgs
    )
    assert "2 open decision(s) — resolve before Dev" in msgs


def test_open_decisions_none_variants_pass(code_doc):
    kb_dir, rev = code_doc
    for word in ("none", "None", "N/A", "n/a"):
        report = run(ticket(grounding(rev, **{"Open decisions": [word]})), kb_dir)
        assert not any("open decision" in e for e in errors(report)), word


def test_inline_open_decision_counts_too(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, **{"Open decisions": "retry policy unknown"})), kb_dir
    )
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
    text = ticket(
        grounding(
            rev,
            Tables="db.restrictive_airspace.brand_new [NEW: column arrives with this ticket]",
        )
    )
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
    assert any(
        "column 'nope'" in e and "db.restrictive_airspace" in e and "(line 11)" in e
        for e in errors(bad)
    )
    good = run(
        ticket(grounding(rev, Tables="db.restrictive_airspace.effective_date")), kb_dir
    )
    assert not any("column" in e for e in errors(good))


def test_route_must_be_a_row_of_the_tag_table(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Routes="api.airspace — DELETE /airspace")), kb_dir)
    assert any(
        "route 'DELETE /airspace'" in e and "api.airspace" in e and "(line 12)" in e
        for e in errors(bad)
    )
    good = run(ticket(grounding(rev, Routes="api.airspace — POST /airspace")), kb_dir)
    assert not any("route" in e for e in errors(good))


def test_backticked_route_is_accepted(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, Routes="api.airspace — `GET /airspace`")), kb_dir
    )
    assert not any("route" in e for e in errors(report))


def test_tag_without_a_route_pair_is_accepted(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Routes="api.airspace")), kb_dir)
    assert not any("route" in e for e in errors(report))


def test_command_must_be_primary_or_an_alternative_verbatim(code_doc):
    kb_dir, rev = code_doc
    bad = run(
        ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest -q`"})), kb_dir
    )
    assert any("command not in cmd.test" in e and "(line 14)" in e for e in errors(bad))
    alt = run(ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest`"})), kb_dir)
    assert not any("command" in e for e in errors(alt))
    other = run(
        ticket(grounding(rev, **{"Verify with": "cmd.lint — `ruff check src`"})), kb_dir
    )
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
    good = run(
        ticket(grounding(rev, **{"Verify with": "`cmd.test` — `pytest`"})), kb_dir
    )
    assert not any("command" in e for e in errors(good))
    bad = run(ticket(grounding(rev, **{"Verify with": "`cmd.test` — `nope`"})), kb_dir)
    msgs = errors(bad)
    assert any(
        "command not in cmd.test" in m and "found:" in m and "`nope`" in m for m in msgs
    )


def test_route_trailing_punctuation_is_tolerated(code_doc):
    kb_dir, rev = code_doc
    good = run(
        ticket(grounding(rev, Routes="api.airspace — GET /airspace, POST /airspace.")),
        kb_dir,
    )
    assert not any("route" in e for e in errors(good))
    bad = run(ticket(grounding(rev, Routes="api.airspace — DELETE /airspace")), kb_dir)
    assert any(
        "route 'DELETE /airspace'" in e and "GET /airspace" in e for e in errors(bad)
    )


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
    assert any(
        "db.restrictive_airspace" in w and "skipped" in w for w in warnings(report)
    )


# --- Task 4: Files vs struct.tree -------------------------------------------


def test_files_present_missing_and_new(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Files=[
                "src/airspace/service.py",
                "db/migration/V1__create_airspace.sql",
                "src/airspace/ghost.py",
                "src/airspace/approval.py [NEW: created by this ticket]",
            ],
        )
    )
    report = run(text, kb_dir)
    msgs = errors(report)
    assert any(
        "file 'src/airspace/ghost.py' not in struct.tree" in m and "(line 12)" in m
        for m in msgs
    )
    assert not any("service.py" in m or "V1__create" in m for m in msgs)
    assert any(
        "new: src/airspace/approval.py — created by this ticket" in n
        for n in notes(report)
    )


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
    report = run(
        ticket(grounding(rev, Files=["src/airspace", "db/migration/"])), kb_dir
    )
    assert not any("not in struct.tree" in e for e in errors(report))


def _drop_struct_files(kb_dir: Path) -> None:
    """Make the doc look like a pre-struct.files code-ingest."""
    path = kb_dir / "demo-code" / "_manifest.yaml"
    manifest = models.load_yaml_model(path, models.Manifest)
    manifest.sections = [
        s for s in manifest.sections if not s.id.startswith("struct.files.")
    ]
    models.save_yaml_model(path, manifest)


def test_path_beyond_depth_cap_is_a_warning_not_an_error(code_doc):
    kb_dir, rev = code_doc
    _drop_struct_files(kb_dir)
    report = run(
        ticket(grounding(rev, Files=["src/airspace/deep/deeper/x.py"])), kb_dir
    )
    assert not any("not in struct.tree" in e for e in errors(report))
    assert any(
        "cannot verify 'src/airspace/deep/deeper/x.py'" in w and "depth" in w
        for w in warnings(report)
    )


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
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"
        )
    )
    rev = models.load_yaml_model(
        kb_dir / "demo-code" / "_manifest.yaml", models.Manifest
    ).revision
    raw = (kb_dir / "demo-code" / "structure.raw.md").read_text(encoding="utf-8")
    assert "more entries omitted" in raw  # precondition: the cap fired
    _drop_struct_files(kb_dir)
    report = run(
        ticket(grounding(rev, Files=["wide/f0699.txt", "wide/f0000.txt", "aaa.txt"])),
        kb_dir,
    )
    # The listing is truncated, so an absent path can never be proven absent:
    # f0699 (past the cut) and aaa.txt (would sort before it, but the marker
    # names a bare file name, so order is not comparable) are both warnings;
    # f0000 is listed → ok. No false errors on a capped tree.
    assert any(
        "cannot verify 'wide/f0699.txt'" in w and "line cap" in w
        for w in warnings(report)
    )
    assert any(
        "cannot verify 'aaa.txt'" in w and "line cap" in w for w in warnings(report)
    )
    assert not any("f0000" in e for e in errors(report))
    assert not any("not in struct.tree" in e for e in errors(report))


def test_missing_structure_raw_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "structure.raw.md").unlink()
    report = run(ticket(grounding(rev)), kb_dir)
    assert not any("struct.tree" in e for e in errors(report))
    assert any(
        "structure.raw.md" in w and "file checks skipped" in w for w in warnings(report)
    )


# --- Task 1 (greenfield): [NEW: D<n>] against the parent mission ----------


def test_parse_decisions_reads_id_status_owner_by_header_name():
    table = ticketcheck.parse_decisions(MISSION, "missions/M-demo.md")
    assert table.source == "missions/M-demo.md"
    assert table.rows["D1"] == ticketcheck.Decision(
        "D1", "DECIDED", "tech-lead", ("M-demo-US1",)
    )
    assert table.rows["D2"].status == "OPEN"


def test_parse_decisions_reads_supersedes():
    text = (
        "## Technology decisions\n"
        "| # | Decision | Status | Owner | Blocks |\n"
        "|---|---|---|---|---|\n"
        "| D1 | Use RabbitMQ | SUPERSEDED | ana | US2 |\n"
        "| D3 | Use Kafka \u2014 Supersedes D1 | DECIDED | ana | US2 |\n"
    )
    rows = ticketcheck.parse_decisions(text, "x").rows
    assert rows["D3"].supersedes == "D1"
    assert rows["D1"].supersedes is None


def test_ticket_check_new_marker_on_superseded_row_names_successor(code_doc):
    kb_dir, rev = code_doc
    mission = (
        MISSION.replace("| D1 | New svc.billing", "| D1 | Old svc.billing").replace(
            "charges per flight plan | DECIDED", "charges per flight plan | SUPERSEDED"
        )
        + "| D3 | New svc.billing v2 \u2014 Supersedes D1 | DECIDED | tech-lead | M-demo-US1 |\n"
    )
    text = ticket(grounding(rev, Externals="int.stripe [NEW: D1]"), parent="M-demo")
    report = run(text, kb_dir, load_decisions=decisions_of(mission))
    msgs = [e for e in errors(report) if "D1" in e]
    assert msgs and "D1 is SUPERSEDED by D3 \u2014 cite D3" in msgs[0]


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
        grounding(
            rev,
            Service="svc.billing [NEW: D1]",
            Files=["src/billing/ [NEW: D1]"],
            Volumes=None,
            Healthchecks=None,
            Devices=None,
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert errors(report) == [], report.render("Grounding")
    assert any(
        "new: svc.billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report)
    )
    assert any(
        "new: src/billing — D1 (DECIDED, owner tech-lead)" in n for n in notes(report)
    )


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
    assert any(
        "decision D9 not in missions/M-demo.md's Technology decisions" in e
        for e in errors(report)
    )


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
    assert any(
        "not found under missions/ or in the hub's plan — pass the mission "
        "(CLI --missions-dir, MCP mission_markdown)" in e
        for e in errors(report)
    )


def test_free_text_new_with_a_decisions_table_present_warns(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Externals="int.stripe [NEW: billing arrives later]"),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert report.passed is True
    assert any("reference the row as [NEW: D<n>]" in w for w in warnings(report))


def test_free_text_new_without_a_parent_mission_stays_a_plain_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives later]"))
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("[NEW: D<n>]" in w for w in warnings(report))
    assert any("new: int.stripe — billing arrives later" in n for n in notes(report))


def test_two_ids_under_one_new_marker_report_the_error_once(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Tables="db.invoice, db.line_item [NEW: D2]"),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    msgs = [e for e in errors(report) if "decision D2 is OPEN" in e]
    assert len(msgs) == 1, errors(report)


def test_two_ids_under_one_new_marker_report_the_free_text_warning_once(code_doc):
    kb_dir, rev = code_doc
    text = ticket(
        grounding(rev, Tables="db.invoice, db.line_item [NEW: later]"),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    warns = [w for w in warnings(report) if "[NEW: D<n>]" in w]
    assert len(warns) == 1, warnings(report)
    new_notes = [n for n in notes(report) if n.startswith("new:")]
    assert len(new_notes) == 2, notes(report)


# --- Task 2 (greenfield): mission heading -----------------------------------


def services_and_order(rev: str, second_row: str) -> str:
    return (
        f"- Grounded on: demo:demo-code @ {rev}\n"
        "\n"
        "| Order | Service | Depends on | Why this order |\n"
        "|---|---|---|---|\n"
        "| 1 | svc.airspace-service | — | base |\n"
        f"| 2 | {second_row} | svc.airspace-service | needs airspace |\n"
    )


def mission_with_services(rev: str, second_row: str) -> str:
    return (
        MISSION
        + f"\n{ticketcheck.SERVICES_HEADING}\n"
        + services_and_order(rev, second_row)
        + "\n"
    )


def test_mission_heading_resolves_decisions_from_the_same_file(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.billing [NEW: D1]")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert errors(report) == [], report.render("Grounding")
    assert any("new: svc.billing — D1 (DECIDED" in n for n in notes(report))


def test_mission_heading_open_decision_fails(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.invoicing [NEW: D2]")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert any("decision D2 is OPEN (owner: Alice)" in e for e in errors(report))


def test_mission_heading_does_not_warn_about_a_service_line(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.airspace-service")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert warnings(report) == [], report.render("Grounding")


def test_mission_heading_unknown_service_is_still_an_error(code_doc):
    kb_dir, rev = code_doc
    text = mission_with_services(rev, "svc.nope")
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert any("unknown id 'svc.nope'" in e for e in errors(report))


def test_mission_heading_grounded_on_list_grounds_on_the_code_entry(code_doc):
    kb_dir, rev = code_doc
    text = (
        MISSION
        + f"\n{ticketcheck.SERVICES_HEADING}\n"
        + (
            f"- Grounded on: demo:demo-code @ {rev}, demo:demo-svc @ {rev}\n"
            "\n"
            "| Order | Service | Depends on | Why this order |\n"
            "|---|---|---|---|\n"
            "| 1 | svc.airspace-service | — | base |\n"
        )
        + "\n"
    )
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert errors(report) == [], report.render("Grounding")
    assert any("demo-code read from" in n for n in notes(report))


def test_mission_heading_grounded_on_list_picks_the_code_entry_wherever_it_is(code_doc):
    kb_dir, rev = code_doc
    text = (
        MISSION
        + f"\n{ticketcheck.SERVICES_HEADING}\n"
        + (
            f"- Grounded on: demo:demo-svc @ {rev}, demo:demo-code @ {rev}\n"
            "\n"
            "| Order | Service | Depends on | Why this order |\n"
            "|---|---|---|---|\n"
            "| 1 | svc.airspace-service | — | base |\n"
        )
        + "\n"
    )
    report = run(text, kb_dir, heading=ticketcheck.SERVICES_HEADING)
    assert errors(report) == [], report.render("Grounding")
    assert any("demo-code read from" in n for n in notes(report))


def test_ticket_heading_grounded_on_list_is_still_rejected(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(
            grounding(
                rev, **{"Grounded on": "demo:demo-code @ {rev}, demo:demo-svc @ {rev}"}
            )
        ),
        kb_dir,
    )
    assert len(errors(report)) == 1
    assert "Grounded on:" in errors(report)[0]


# --- compose facts: Volumes / Healthchecks / Devices (spec 2026-09-23) ----

TWO_SVC = "svc.airspace-service, svc.postgres"


def test_golden_compose_facts_pass(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev)), kb_dir)
    assert errors(report) == [], report.render("Grounding")
    assert not any("Volumes:/Healthchecks:/Devices:" in w for w in warnings(report))


def test_volume_not_on_the_service_is_an_error(code_doc):
    kb_dir, rev = code_doc
    bad = run(
        ticket(
            grounding(
                rev, Service=TWO_SVC, Volumes="svc.postgres — myflix-postgres-data"
            )
        ),
        kb_dir,
    )
    assert any(
        e
        == "volume 'myflix-postgres-data' is not in svc.postgres (has: pgdata) (line 17)"
        for e in errors(bad)
    )
    good = run(
        ticket(grounding(rev, Service=TWO_SVC, Volumes="svc.postgres — pgdata")), kb_dir
    )
    assert not any("volume" in e for e in errors(good))


def test_healthcheck_must_match_verbatim(code_doc):
    kb_dir, rev = code_doc
    bad = run(
        ticket(
            grounding(
                rev,
                Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/api/health`",
            )
        ),
        kb_dir,
    )
    assert any(
        e
        == "healthcheck for svc.airspace-service is 'curl -f http://localhost:8080/health', not 'curl -f http://localhost:8080/api/health' (line 18)"
        for e in errors(bad)
    )
    none_bad = run(
        ticket(
            grounding(
                rev,
                Service=TWO_SVC,
                Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/health`; svc.postgres — `pg_isready`",
            )
        ),
        kb_dir,
    )
    assert any("healthcheck for svc.postgres is 'none'" in e for e in errors(none_bad))
    none_good = run(
        ticket(
            grounding(
                rev,
                Service=TWO_SVC,
                Healthchecks="svc.airspace-service — `curl -f http://localhost:8080/health`; svc.postgres — none",
            )
        ),
        kb_dir,
    )
    assert not any("healthcheck" in e for e in errors(none_good))


def test_healthcheck_url_is_never_read_as_a_section_id(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(
            grounding(
                rev,
                Healthchecks="svc.airspace-service — `curl -f http://api.internal/health`",
            )
        ),
        kb_dir,
    )
    assert not any("unknown id 'api.internal" in e for e in errors(report))


def test_device_not_on_the_service_is_an_error(code_doc):
    kb_dir, rev = code_doc
    bad = run(
        ticket(grounding(rev, Service=TWO_SVC, Devices="svc.postgres — nvidia:gpu")),
        kb_dir,
    )
    assert any(
        e == "device 'nvidia:gpu' is not in svc.postgres (has: none) (line 19)"
        for e in errors(bad)
    )


def test_new_marker_exempts_a_compose_value(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(
            grounding(
                rev,
                Service=TWO_SVC,
                Volumes="svc.postgres — pgdata, myflix-minio-data [NEW: D1]",
            ),
            parent="M-demo",
        ),
        kb_dir,
        load_decisions=decisions_of(MISSION),
    )
    assert not any("volume" in e for e in errors(report))
    assert any("new: myflix-minio-data — D1 (DECIDED" in n for n in notes(report))


def test_svc_on_a_compose_line_must_be_on_the_service_line(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Volumes="svc.postgres — pgdata")), kb_dir)
    assert any(
        e == "svc.postgres on the Volumes: line is not on the Service: line (line 17)"
        for e in errors(report)
    )


def test_whole_line_none_while_the_service_has_volumes_warns(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Service=TWO_SVC, Volumes="none")), kb_dir)
    assert errors(report) == []
    assert any(
        w == "svc.postgres has volumes the grounding omits: pgdata (line 17)"
        for w in warnings(report)
    )


def test_missing_compose_lines_are_a_warning_not_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, Volumes=None, Healthchecks=None, Devices=None)), kb_dir
    )
    assert errors(report) == []
    assert any(
        w
        == "Volumes:/Healthchecks:/Devices: lines missing — re-ground on a -code revision that carries them"
        for w in warnings(report)
    )


def test_old_code_doc_without_the_rows_skips_with_a_note(code_doc, tmp_path):
    kb_dir, rev = code_doc
    services_md = kb_dir / "demo-code" / "services.md"
    text = services_md.read_text(encoding="utf-8")
    text = "\n".join(
        ln
        for ln in text.splitlines()
        if not ln.startswith(("| Volumes |", "| Healthcheck |", "| Devices |"))
    )
    services_md.write_text(text + "\n", encoding="utf-8")
    report = run(ticket(grounding(rev, Volumes="svc.airspace-service — ghost")), kb_dir)
    assert not any("volume" in e for e in errors(report))
    assert any(
        n
        == "demo-code has no Volumes/Healthcheck/Devices rows (pre-1.3.0 code-ingest) — compose-fact checks skipped"
        for n in notes(report)
    )


def test_new_service_compose_line_does_not_trigger_the_pre_1_3_0_note(code_doc):
    """A greenfield [NEW] service isn't in the -code manifest at all — that
    is a different situation from an old document missing the compose rows,
    and must not be reported as one (review finding #1)."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Service="svc.airspace-service, svc.billing [NEW: D1]",
            Volumes="svc.billing — data [NEW: D1]",
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("compose-fact checks skipped" in n for n in notes(report))
    assert not any("volume" in e for e in errors(report))
    assert any("new: svc.billing — D1 (DECIDED" in n for n in notes(report))


def test_real_error_and_new_service_on_one_line_do_not_add_a_contradicting_skip_note(
    code_doc,
):
    """A real error for a known service and a [NEW] service must not be
    collapsed into one contradictory "checks skipped" note (review finding
    #1)."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Service=f"{TWO_SVC}, svc.billing [NEW: D1]",
            Volumes="svc.postgres — ghost; svc.billing — data [NEW: D1]",
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any("volume 'ghost' is not in svc.postgres" in e for e in errors(report))
    assert not any("compose-fact checks skipped" in n for n in notes(report))


def test_healthcheck_semicolon_in_a_shell_command_is_not_truncated(code_doc):
    """A `;` inside a backticked healthcheck command must not cut the value
    short, nor leak a stray backtick into the error (review finding #2)."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev, Healthchecks="svc.airspace-service — `sh -c 'pg_isready; exit 0'`"
        )
    )
    report = run(text, kb_dir)
    msgs = [
        e
        for e in errors(report)
        if e.startswith("healthcheck for svc.airspace-service")
    ]
    assert len(msgs) == 1, errors(report)
    assert "sh -c 'pg_isready; exit 0'" in msgs[0]
    assert "`" not in msgs[0]


def test_unparseable_compose_line_warns_instead_of_passing_silently(code_doc):
    """A compose line that doesn't parse into any `svc.<x> — <values>` group
    (the `svc.` prefix forgotten) must warn, not pass the gate clean (review
    finding #3)."""
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Volumes="pgdata"))
    report = run(text, kb_dir)
    assert errors(report) == []
    assert any(
        w
        == "Volumes: line does not parse — expected `svc.<name> — <values>` (got: pgdata) (line 17)"
        for w in warnings(report)
    )


def test_new_marker_exempts_a_healthcheck_value(code_doc):
    """`[NEW: D<n>]` written after a backticked healthcheck value (the
    natural place for it) must exempt that value, same as it does for
    Volumes/Devices (review finding #4)."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Service=TWO_SVC,
            Healthchecks=(
                "svc.airspace-service — `curl -f http://localhost:8080/health`; "
                "svc.postgres — `pg_isready` [NEW: D1]"
            ),
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("healthcheck" in e for e in errors(report))
    assert any("new: pg_isready — D1 (DECIDED" in n for n in notes(report))


def test_healthcheck_bare_url_is_never_read_as_a_section_id(code_doc):
    """`_split_values` already accepts an un-backticked healthcheck value —
    the id scan must reject it the same way it rejects the backticked form
    (review finding #5)."""
    kb_dir, rev = code_doc
    report = run(
        ticket(
            grounding(
                rev,
                Healthchecks="svc.airspace-service — curl -f http://api.internal/health",
            )
        ),
        kb_dir,
    )
    assert not any("unknown id 'api.internal" in e for e in errors(report))


def test_new_service_healthchecks_line_does_not_report_unknown_id(code_doc):
    """The Healthchecks twin of `test_new_service_compose_line_does_not_
    trigger_the_pre_1_3_0_note`: a greenfield `[NEW]` service named on a
    `Healthchecks:` line must keep its exemption. `_id_lines` blanks a
    Healthchecks value so a bare URL/command isn't read as a section id
    (review finding #5) — that blanking must not also delete the `[NEW: …]`
    marker the id scan relies on to exempt the id (Critical regression)."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Service="svc.airspace-service, svc.billing [NEW: D1]",
            Healthchecks="svc.billing — `pg_isready` [NEW: D1]",
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert not any("unknown id 'svc.billing'" in e for e in errors(report))


def test_new_marker_on_a_multi_value_healthchecks_group_is_ignored(code_doc):
    """`[NEW: …]` after a multi-value Healthchecks group (two backticked
    spans on one `svc.<x> — ` group) is ignored outright: it exempts
    NEITHER value, `extra-check` still errors, and no `[NEW: …]` note is
    emitted (final review, Minor 1 — this test used to be misnamed
    "...exempts_only_its_value", which claims the opposite of what its own
    body proves).

    Known gap, not fixed here: the brief's rule for the single-value case
    ("the marker exempts only the value it sits next to") is never
    extended to the multi-value case — `_check_compose_facts`'s
    `raw_new` fallback is gated on `len(split_values) == 1`, so a marker
    after a multi-value group has no effect at all rather than exempting
    just the value it's adjacent to."""
    kb_dir, rev = code_doc
    text = ticket(
        grounding(
            rev,
            Healthchecks=(
                "svc.airspace-service — `curl -f http://localhost:8080/health`, "
                "`extra-check` [NEW: D1]"
            ),
        ),
        parent="M-demo",
    )
    report = run(text, kb_dir, load_decisions=decisions_of(MISSION))
    assert any(
        "healthcheck for svc.airspace-service" in e and "extra-check" in e
        for e in errors(report)
    )
    assert not any("new:" in n and "curl" in n for n in notes(report))


# --- compose facts: escape-aware Healthcheck cell read-back (final review,
# Critical 1) --------------------------------------------------------------

THREE_SVC = "svc.airspace-service, svc.postgres, svc.gpuworker"
GPUWORKER_HEALTHCHECK = "curl -s http://localhost/health | grep -q ok"


def test_healthcheck_containing_a_pipe_grounds_clean(code_doc):
    """`escape_cell` (services.py) backslash-escapes a literal `|` in the
    Healthcheck L2 cell so a `CMD-SHELL "... | ..."` healthcheck — the most
    common non-trivial healthcheck form — round-trips through the L2 table
    at all. `_property` used to read that cell back through
    `lintcore.table_rows()`, whose `line[1:-1].split("|")` is NOT
    escape-aware and also split on the backslash-escaped pipe, truncating
    the cell before `_property`'s own `.replace("\\|", "|")` ever ran —
    so no value an SA could write for `svc.gpuworker` (fixture: a
    `test: ["CMD-SHELL", "curl -s http://localhost/health | grep -q ok"]`
    healthcheck) ever grounded clean. Reproduced end to end, before the
    fix: `[error] healthcheck for svc.gpuworker is 'curl -s
    http://localhost/health \\', not 'curl -s http://localhost/health \\|
    grep -q ok'` — the error even named the truncated fragment as the
    document's real value. After the fix, the exact compose command
    grounds with zero errors."""
    kb_dir, rev = code_doc

    # Extractor side: the L2 cell really is escaped in the real document.
    services_md = (kb_dir / "demo-code" / "services.md").read_text(encoding="utf-8")
    assert (
        "| Healthcheck | curl -s http://localhost/health \\| grep -q ok |"
        in services_md
    )

    text = ticket(
        grounding(
            rev,
            Service=THREE_SVC,
            Volumes="svc.airspace-service — none; svc.postgres — pgdata; svc.gpuworker — none",
            Healthchecks=(
                "svc.airspace-service — `curl -f http://localhost:8080/health`; "
                "svc.postgres — none; "
                f"svc.gpuworker — `{GPUWORKER_HEALTHCHECK}`"
            ),
            Devices="svc.airspace-service — nvidia:gpu; svc.postgres — none; svc.gpuworker — none",
        )
    )
    report = run(text, kb_dir)
    assert errors(report) == [], report.render("Grounding")


# --- Task 1 (mission next PR 1): Decision.blocks, lintcore.table_column ----


def test_table_column_is_shared_from_lintcore():
    from strata_kb import lintcore

    rows = [
        ["#", "Decision", "Status", "Owner", "Blocks"],
        ["D1", "x", "OPEN", "a", "M-demo-US1"],
    ]
    assert lintcore.table_column(rows, "status") == 2
    assert lintcore.table_column(rows, "Blocks") == 4
    assert lintcore.table_column(rows, "nope") is None
    assert lintcore.table_column([], "status") is None
    assert ticketcheck._table_column is lintcore.table_column


def test_parse_decisions_reads_blocks_column():
    text = (
        "# M\n> Mission: M-demo\n\n## Technology decisions\n"
        "| # | Decision | Status | Owner | Blocks |\n|---|---|---|---|---|\n"
        "| D1 | one | DECIDED | a | M-demo-US1, M-demo-US3 |\n"
        "| D2 | two | OPEN | b | M-other-US2 |\n"
        "| D3 | three | OPEN | c |  |\n"
        "| D4 | four | OPEN | d | US4, M-demo-US1 |\n"
    )
    table = ticketcheck.parse_decisions(text, "m")
    assert table.rows["D1"].blocks == ("M-demo-US1", "M-demo-US3")
    assert table.rows["D2"].blocks == ("M-other-US2",)
    assert table.rows["D3"].blocks == ()
    # A bare `US<n>` stays as written — parse_decisions has no mission id to
    # prefix it with; full ids come first, same order as dep_ids.
    assert table.rows["D4"].blocks == ("M-demo-US1", "US4")


def test_parse_decisions_without_blocks_column_keeps_empty_tuple():
    text = (
        "# M\n> Mission: M-demo\n\n## Technology decisions\n"
        "| # | Decision | Status | Owner |\n|---|---|---|---|\n"
        "| D1 | one | DECIDED | a |\n"
    )
    table = ticketcheck.parse_decisions(text, "m")
    assert table.rows["D1"] == ticketcheck.Decision("D1", "DECIDED", "a", ())


def test_grounded_entries_splits_a_list_and_rejects_a_bad_entry():
    from strata_kb.ticketcheck import grounded_entries

    assert grounded_entries("- Grounded on: demo:demo-code @ ABC1234") == [
        ("demo", "demo-code", "abc1234")
    ]
    assert grounded_entries("- Grounded on: a:a-code @ 1234567, a:a-svc @ 1234567") == [
        ("a", "a-code", "1234567"),
        ("a", "a-svc", "1234567"),
    ]
    assert grounded_entries("- Grounded on: a:a-code @ 1234567, junk") == []
    assert grounded_entries("- Files: x.py") == []


# --- struct.files.* widen the Files: check beyond struct.tree's cap ---------

DEEP = "src/airspace/deep/deeper/x.py"


def _commit_deep_file(tmp_path: Path, run_git, kb_dir: Path):
    """A fresh ingest of the code_doc repo plus one depth-5 tracked file."""
    root = tmp_path / "repo"
    (root / "src/airspace/deep/deeper").mkdir(parents=True)
    (root / DEEP).write_text("x", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "deep")
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"
        )
    )
    return models.load_yaml_model(
        kb_dir / "demo-code" / "_manifest.yaml", models.Manifest
    ).revision


def test_files_check_accepts_path_beyond_depth_4_when_listed(
    code_doc, tmp_path, run_git
):
    kb_dir, _ = code_doc
    rev = _commit_deep_file(tmp_path, run_git, kb_dir)
    report = run(
        ticket(grounding(rev, Files=[DEEP, "src/airspace/deep/deeper"])), kb_dir
    )
    assert not any("not in struct.tree" in e for e in errors(report))
    assert not any("cannot verify" in w for w in warnings(report))


def test_files_check_unknown_deep_path_is_error_when_struct_files_present(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=[DEEP])), kb_dir)
    assert any(f"file '{DEEP}' not in struct.tree" in e for e in errors(report))
    assert not any("cannot verify" in w for w in warnings(report))


def test_structure_adds_files_sections_and_directory_prefixes(
    code_doc, tmp_path, run_git
):
    kb_dir, _ = code_doc
    _commit_deep_file(tmp_path, run_git, kb_dir)
    doc = ticketcheck.load_doc_dir(kb_dir / "demo-code", str(kb_dir / "demo-code"))
    union = ticketcheck._read_structure(doc).paths
    assert {DEEP, "src/airspace/deep/deeper", "src/airspace/deep", "src"} <= union


# --- Task 11: route/page/job/sym citations, [NEW] coverage gate -----------

_COVERAGE = """\
| Area | Scope | Framework/language | Status | Detail |
| --- | --- | --- | --- | --- |
| files | apps | - | complete |  |
| jobs | apps/api | - | partial | jobs outside framework schedulers are not detectable |
| pages | apps/web | Next.js | complete |  |
| routes | apps/api | NestJS | partial | apps/api/src/legacy.controller.ts:4 |
| routes | apps/media | NestJS | complete |  |
| routes | apps/web | Next.js | complete |  |
| schema | . | prisma | complete |  |
| symbols | apps/api | typescript | complete |  |
| symbols | apps/web | css | partial | apps/web/a.css:1 |
| symbols | apps/web | tsx | complete |  |
"""
_MEDIA = "route.apps-media-src-media-controller"
_API = "route.apps-api-src-x-controller"
_PAGES = "page.apps-web"
_JOBS = "job.apps-api-src-maintenance-service-073d57"
_SYMS = "sym.apps-api"
_STRUCT_RAW = (
    "## struct.tree Repository tree\n\n```\n- apps/\n  - apps/media/\n```\n\n"
    "## struct.files.apps Files: apps/\n\n```\napps/media/src/media.controller.ts\n```\n"
)


def _synth_doc(*, coverage: bool = True, revision: str = "abc1234"):
    """A `demo-code` LoadedDoc built from hand-written L2 tables in the real
    section shapes -- no tree-sitter, no ingest."""
    blocks = {
        _MEDIA: (
            "routes",
            "| Method | Path | Handler | File | Request type |\n| --- | --- | --- | --- | --- |\n"
            "| GET | /media/ping | MediaController.ping | apps/media/src/media.controller.ts |  |\n"
            "| GET | /watch/{id} | MediaController.watch | apps/media/src/media.controller.ts |  |\n",
        ),
        _API: (
            "routes",
            "| Method | Path | Handler | File | Request type |\n| --- | --- | --- | --- | --- |\n"
            "| POST | /api/x | X.create | apps/api/src/x.controller.ts |  |\n",
        ),
        _PAGES: (
            "pages",
            "| Path | File | Layout/group |\n| --- | --- | --- |\n"
            "| /admin | apps/web/src/app/(admin)/admin/page.tsx | (admin) |\n"
            "| /watch/[id] | apps/web/src/app/watch/[id]/page.tsx |  |\n"
            "| Middleware matcher: /admin/:path* | apps/web/src/middleware.ts |  |\n",
        ),
        _JOBS: (
            "jobs",
            "| Name | Schedule | Handler | File |\n| --- | --- | --- | --- |\n"
            "| createPartition | 0 3 * * * | M.createPartition | apps/api/src/m.ts |\n"
            "| nightly cleanup | 0 2 * * * | - | apps/api/src/m.ts |\n"
            "| (anonymous) | 0 4 * * * | - | apps/api/src/m.ts |\n"
            "| (anonymous) | 0 5 * * * | - | apps/api/src/m.ts |\n",
        ),
        "sym.apps-web": (
            "symbols",
            "| Name | Kind | File |\n| --- | --- | --- |\n"
            "| --brand | css-variable | apps/web/src/a.css |\n",
        ),
        _SYMS: (
            "symbols",
            "| Name | Kind | File |\n| --- | --- | --- |\n"
            "| AdminController | class | apps/api/src/admin.controller.ts |\n",
        ),
    }
    if coverage:
        blocks["struct.coverage"] = ("structure", _COVERAGE)
    groups: dict[str, str] = {}
    for sid, (group, body) in blocks.items():
        groups[group] = groups.get(group, "") + f"## {sid} title\n\n{body}\n"
    manifest = models.Manifest(
        id="demo-code",
        title="demo",
        revision=revision,
        sections=[
            models.SectionEntry(id=sid, title=sid, file=group)
            for sid, (group, _) in blocks.items()
        ]
        + [
            models.SectionEntry(id="struct.tree", title="t", file="structure"),
            models.SectionEntry(id="struct.files.apps", title="f", file="structure"),
        ],
    )
    return ticketcheck.LoadedDoc(
        manifest=manifest,
        source="synthetic",
        read_group=groups.get,
        read_raw=lambda g: _STRUCT_RAW if g == "structure" else None,
    )


def run_synth(
    lines: list[str], *, doc=None, grounded="abc1234", **kwargs
) -> LintReport:
    doc = doc or _synth_doc()
    body = "\n".join(
        [
            f"- Grounded on: demo:demo-code @ {grounded}",
            "- Open decisions: none",
            *lines,
        ]
    )
    return ticketcheck.check(ticket(body), load_doc=lambda repo, d: doc, **kwargs)


@pytest.mark.parametrize(
    "raw",
    [
        "/watch/:id",
        "/watch/{id}",
        "/watch/{id:int}",
        "/watch/<int:id>",
        "/watch/<id>",
        "/watch/[id]",
        "/watch/:id/",
    ],
)
def test_normalise_path_unifies_param_syntaxes(raw):
    assert ticketcheck.normalise_path(raw) == "/watch/{}"


def test_normalise_path_catch_all_and_root():
    assert ticketcheck.normalise_path("/docs/[...slug]") == "/docs/{}"
    assert ticketcheck.normalise_path("/") == "/"


def test_route_citation_from_code_verified():
    ok = run_synth([f"- Routes: {_MEDIA} — GET /media/ping"])
    assert errors(ok) == [], ok.render("Grounding")
    bad = run_synth([f"- Routes: {_MEDIA} — POST /media/ping"])
    (msg,) = errors(bad)
    assert f"route 'POST /media/ping' is not in {_MEDIA}" in msg
    assert "GET /media/ping" in msg and "(line 9)" in msg


def test_route_param_syntax_normalised():
    report = run_synth([f"- Routes: {_MEDIA} — GET /watch/:id"])
    assert errors(report) == [], report.render("Grounding")


def test_page_job_symbol_citations_verified():
    good = run_synth(
        [
            f"- Pages: {_PAGES} — /watch/:id",
            f"- Jobs: {_JOBS} — `createPartition`",
            f"- Symbols: {_SYMS} — AdminController (route handlers)",
        ]
    )
    assert errors(good) == [], good.render("Grounding")
    bad = run_synth(
        [
            f"- Pages: {_PAGES} — /nowhere",
            f"- Jobs: {_JOBS} — nightlyExport",
            f"- Symbols: {_SYMS} — Ghost",
        ]
    )
    msgs = errors(bad)
    assert len(msgs) == 3, msgs
    assert "page '/nowhere' is not in page.apps-web" in msgs[0]
    assert "/admin" in msgs[0] and "/watch/{}" not in msgs[0]
    assert "job 'nightlyExport' is not in " + _JOBS in msgs[1]
    assert "createPartition" in msgs[1]
    assert "symbol 'Ghost' is not in sym.apps-api" in msgs[2]
    assert "AdminController" in msgs[2]


def test_middleware_matcher_row_is_not_a_page():
    report = run_synth([f"- Pages: {_PAGES} — /admin/:path*"])
    assert any("is not in page.apps-web" in e for e in errors(report))


def test_placeholder_job_names_never_match():
    report = run_synth([f"- Jobs: {_JOBS} — (anonymous)"])
    (msg,) = errors(report)
    assert "job '(anonymous)' is not in" in msg
    assert "(anonymous)" not in msg.split("copy a Name")[1]


def test_new_rejected_when_scope_partial():
    report = run_synth(
        ["- Routes: GET /api/new in apps/api/src/new.controller.ts [NEW: tbd]"]
    )
    assert (
        "cannot claim new: coverage of apps/api (routes) is partial; "
        "move it to Open decisions (line 9)"
    ) in errors(report)


def test_new_rejected_when_scope_not_scanned():
    report = run_synth(["- Pages: /x in `apps/other/app/x/page.tsx` [NEW: tbd]"])
    assert any(
        "coverage of apps/other/app/x/page.tsx (pages) is not scanned" in e
        for e in errors(report)
    ), errors(report)


def test_new_allowed_when_scope_complete():
    report = run_synth(
        ["- Routes: GET /media/fresh in apps/media/src/fresh.controller.ts [NEW: tbd]"]
    )
    assert errors(report) == [], report.render("Grounding")
    assert any("GET /media/fresh" in n for n in notes(report))


def test_new_on_jobs_always_rejected():
    report = run_synth(["- Jobs: nightly in apps/media/src/job.ts [NEW: tbd]"])
    assert any(
        "cannot claim new: coverage of " in e and "(jobs) is not scanned" in e
        for e in errors(report)
    )
    # a scope whose row says partial reports partial
    partial = run_synth(["- Jobs: nightly in apps/api/src/job.ts [NEW: tbd]"])
    assert any("coverage of apps/api (jobs) is partial" in e for e in errors(partial))
    # even a document that carries no struct.coverage at all
    bare = run_synth(
        ["- Jobs: nightly in apps/media/src/job.ts [NEW: tbd]"],
        doc=_synth_doc(coverage=False),
    )
    assert any(
        "cannot claim new: coverage of" in e and "(jobs)" in e for e in errors(bare)
    )


def test_new_requires_target_file():
    report = run_synth(["- Symbols: Fresh [NEW: tbd]"])
    assert (
        "[NEW] in Symbols must name the file it will live in "
        "(… in <path> [NEW: D<n>]) (line 9)"
    ) in errors(report)


def test_new_files_gate_uses_top_level_directory():
    ok = run_synth(["- Files: apps/media/src/fresh.ts [NEW: tbd]"])
    assert errors(ok) == [], ok.render("Grounding")
    root = run_synth(["- Files: Dockerfile [NEW: tbd]"])
    assert any("coverage of . (files) is not scanned" in e for e in errors(root))
    other = run_synth(["- Files: tools/x.ts [NEW: tbd]"])
    assert any("coverage of tools (files) is not scanned" in e for e in errors(other))


def test_doc_without_struct_coverage_skips_coverage_gate():
    report = run_synth(
        ["- Routes: GET /api/new in apps/api/src/n.controller.ts [NEW: tbd]"],
        doc=_synth_doc(coverage=False),
    )
    assert errors(report) == [], report.render("Grounding")


def test_new_marker_decision_is_still_judged():
    report = run_synth(
        ["- Routes: GET /media/fresh in apps/media/src/f.ts [NEW: D9]"],
        load_decisions=decisions_of(MISSION),
    )
    # no parent mission in the ticket -> the D-ref cannot be verified
    assert any("[NEW: D9] needs a parent mission" in e for e in errors(report))


def test_new_on_existing_route_is_error_at_same_revision():
    report = run_synth(
        ["- Routes: GET /watch/:id in apps/media/src/media.controller.ts [NEW: tbd]"]
    )
    assert (
        f"route 'GET /watch/:id' already exists in {_MEDIA}; cite it instead (line 9)"
    ) in errors(report)


def test_new_on_existing_page_symbol_and_file_is_error():
    report = run_synth(
        [
            "- Pages: /admin in `apps/web/x/page.tsx` [NEW: tbd]",
            "- Symbols: AdminController in apps/api/src/admin.controller.ts [NEW: tbd]",
            "- Files: apps/media/src/media.controller.ts [NEW: tbd]",
        ]
    )
    msgs = errors(report)
    assert any(f"already exists in {_PAGES}" in m for m in msgs)
    assert any(f"already exists in {_SYMS}" in m for m in msgs)
    assert any("already exists in struct.files.apps" in m for m in msgs)


LISTED_LINE = ["- Routes: GET /media/ping in apps/media/src/p.ts [NEW: tbd]"]


def _old_ref(content: str) -> ResolvedRef:
    return ResolvedRef(
        ref=KBRef(repo_id="demo", doc_id="demo-code", section_id=_MEDIA),
        status="ok",
        citation=f"demo-code §{_MEDIA}",
        content=content,
        tokens=0,
    )


def test_new_on_existing_thing_is_note_when_listed_only_after_grounded_rev():
    seen: list[tuple] = []

    def load_at(repo, doc_id, rev, ids):
        seen.append((repo, doc_id, rev, ids))
        return [_old_ref("| Method | Path |\n| --- | --- |\n| GET | /media/other |\n")]

    report = run_synth(LISTED_LINE, grounded="deadbee", load_at=load_at)
    assert seen == [("demo", "demo-code", "deadbee", [_MEDIA])]
    assert not any("already exists" in e for e in errors(report))
    assert any(
        f"route 'GET /media/ping' now exists in {_MEDIA} — built since grounding" in n
        for n in notes(report)
    )


def test_new_on_thing_listed_at_grounded_rev_is_error_even_when_moved():
    body = "| Method | Path |\n| --- | --- |\n| GET | /media/ping |\n"
    report = run_synth(
        LISTED_LINE, grounded="deadbee", load_at=lambda *a: [_old_ref(body)]
    )
    assert any(
        f"already exists in {_MEDIA}; cite it instead" in e for e in errors(report)
    )


@pytest.mark.parametrize("outcome", ["none", "raises", "no-loader"])
def test_new_on_existing_thing_without_a_baseline_is_a_note(outcome):
    def load_at(*a):
        if outcome == "raises":
            raise KbError("no baseline")
        return None

    report = run_synth(
        LISTED_LINE,
        grounded="deadbee",
        load_at=None if outcome == "no-loader" else load_at,
    )
    assert not any("already exists" in e for e in errors(report))
    assert any("now exists in" in n for n in notes(report))


def test_files_not_found_message_names_struct_files_when_that_proved_absence(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/airspace/ghost.py"])), kb_dir)
    assert any(
        "file 'src/airspace/ghost.py' not in struct.tree" in e and "struct.files" in e
        for e in errors(report)
    )


def test_existing_ticket_fixtures_unchanged_with_real_coverage(code_doc):
    kb_dir, rev = code_doc
    report = run(
        ticket(grounding(rev, Files=["src/airspace/approval.py [NEW: made here]"])),
        kb_dir,
    )
    assert errors(report) == [], report.render("Grounding")


# --- Task 11 fix round 1 --------------------------------------------------


def test_two_route_ids_on_one_line_are_checked_separately():
    line = f"- Routes: {_MEDIA} — GET /media/ping, {_API} — POST /api/x"
    report = run_synth([line])
    assert errors(report) == [], report.render("Grounding")
    swapped = run_synth([f"- Routes: {_MEDIA} — POST /api/x, {_API} — GET /media/ping"])
    msgs = errors(swapped)
    assert len(msgs) == 2, msgs
    assert f"is not in {_MEDIA}" in msgs[0] and f"is not in {_API}" in msgs[1]


@pytest.mark.parametrize(
    "fname",
    [
        "users.route.ts",
        "+page.svelte",
        "+page.server.ts",
        "export.job.ts",
        "a-sym.x.ts",
    ],
)
def test_file_names_are_never_read_as_section_ids(fname):
    prose = run_synth([f"- Routes: {_MEDIA} — GET /media/ping (handled in {fname})"])
    assert errors(prose) == [], errors(prose)
    target = run_synth(
        [f"- Routes: GET /media/fresh in apps/media/src/{fname} [NEW: tbd]"]
    )
    assert errors(target) == [], errors(target)
    assert any(n.startswith("new: GET /media/fresh") for n in notes(target))


def test_structure_is_read_once_per_check():
    doc = _synth_doc()
    reads: list[str] = []

    def read_raw(group):
        reads.append(group)
        return doc.read_raw(group)

    counted = ticketcheck.LoadedDoc(doc.manifest, doc.source, doc.read_group, read_raw)
    run_synth(
        [
            "- Files:",
            "  - apps/media/src/media.controller.ts",
            "  - apps/media/src/fresh.ts [NEW: tbd]",
        ],
        doc=counted,
    )
    assert reads == ["structure"]


def test_exists_label_has_no_code_span_backticks():
    report = run_synth(
        ["- Symbols: `AdminController` in apps/api/src/admin.controller.ts [NEW: tbd]"]
    )
    assert any(
        e.startswith("symbol 'AdminController' already exists") for e in errors(report)
    )


def test_unscoped_target_names_the_path():
    report = run_synth(["- Symbols: Foo in tools/gen/foo.ts [NEW: tbd]"])
    assert any(
        "coverage of tools/gen/foo.ts (symbols) is not scanned" in e
        for e in errors(report)
    )


def test_multi_row_scope_uses_the_row_matching_the_file_language():
    # apps/web symbols: css partial, tsx complete
    ok = run_synth(["- Symbols: Foo in apps/web/src/foo.tsx [NEW: tbd]"])
    assert errors(ok) == [], errors(ok)
    bad = run_synth(["- Symbols: --x in apps/web/src/theme.css [NEW: tbd]"])
    assert any(
        "coverage of apps/web (symbols, css) is partial" in e for e in errors(bad)
    ), errors(bad)
    # language not determinable (.md): worst row of the scope decides
    worst = run_synth(["- Symbols: Foo in apps/web/src/foo.md [NEW: tbd]"])
    assert any(
        "coverage of apps/web (symbols, css) is partial" in e for e in errors(worst)
    )


# --- Task 11 fix round 2 --------------------------------------------------


@pytest.mark.parametrize(
    ("field", "sid", "good", "bad"),
    [
        ("Routes", _MEDIA, "GET /media/ping", "GET /bogus"),
        ("Pages", _PAGES, "/admin", "/bogus"),
        ("Jobs", _JOBS, "`createPartition`", "`nope`"),
        ("Symbols", _SYMS, "`AdminController`", "`Ghost`"),
    ],
)
def test_repeated_id_checks_every_segment(field, sid, good, bad):
    ok = run_synth([f"- {field}: {sid} — {good}, {sid} — {good}"])
    assert errors(ok) == [], errors(ok)
    report = run_synth([f"- {field}: {sid} — {good}, {sid} — {bad}"])
    (msg,) = errors(report)
    assert f"is not in {sid}" in msg, msg


@pytest.mark.parametrize(
    ("field", "sid", "cite"),
    [
        ("Routes", _MEDIA, "GET /media/ping"),
        ("Pages", _PAGES, "/admin"),
        ("Jobs", _JOBS, "`createPartition`"),
        ("Symbols", _SYMS, "`AdminController`"),
    ],
)
def test_citation_before_the_first_id_is_not_attached(field, sid, cite):
    report = run_synth([f"- {field}: {cite} via {sid}"])
    (msg,) = errors(report)
    assert "not attached to a section id" in msg and "(line 9)" in msg, msg


def test_citation_before_first_id_is_judged_per_line_not_per_segment():
    report = run_synth(
        [f"- Routes: GET /x via {_MEDIA} — GET /media/ping, {_API} — POST /api/x"]
    )
    assert sum("not attached" in e for e in errors(report)) == 1


def test_backticked_job_name_with_spaces_is_kept_whole():
    exists = run_synth(["- Jobs: `nightly cleanup` in apps/api/src/n.ts [NEW: tbd]"])
    assert any(
        "job 'nightly cleanup' already exists in " + _JOBS in e for e in errors(exists)
    ), errors(exists)
    cited = run_synth([f"- Jobs: {_JOBS} — `nightly cleanup`"])
    assert errors(cited) == [], errors(cited)


def test_css_variable_keeps_its_dashes():
    exists = run_synth(["- Symbols: --brand in apps/web/src/b.css [NEW: tbd]"])
    assert any(
        "symbol '--brand' already exists in sym.apps-web" in e for e in errors(exists)
    ), errors(exists)
    cited = run_synth(["- Symbols: sym.apps-web — --brand"])
    assert errors(cited) == [], errors(cited)


def test_coverage_languages_come_from_the_extractor_table():
    from strata_kb.codeingest.extractors import _ts

    assert not hasattr(ticketcheck, "_EXT_LANGUAGE")
    assert ticketcheck.LANG_BY_SUFFIX is _ts.LANG_BY_SUFFIX


@pytest.mark.parametrize(
    "name",
    [
        "route.ts",
        "page.tsx",
        "job.ts",
        "sym.css",
        "db.ts",
        "api.js",
        "struct.md",
        "cmd.py",
        "int.json",
    ],
)
def test_bare_framework_file_names_are_never_ids(name):
    for tail in (f"(see {name})", f"see {name}.", f"see {name}, then"):
        report = run_synth([f"- Routes: {_MEDIA} — GET /media/ping {tail}"])
        assert errors(report) == [], (tail, errors(report))


def test_ids_that_merely_start_like_an_extension_still_count():
    report = run_synth([f"- Routes: {_MEDIA} — GET /media/ping, route.tsx-extra"])
    assert any("unknown id 'route.tsx-extra'" in e for e in errors(report))
    report = run_synth(["- Routes: db.json_events"])
    assert any("unknown id 'db.json_events'" in e for e in errors(report))


# --- Task 12: drift judges the new citations -------------------------------


def _synth_ref(sid: str, status: str) -> ResolvedRef:
    return _drift_ref(sid, status, "OLD\n")


def test_moved_revision_route_citation_still_valid_is_pass_note():
    report = run_synth(
        [f"- Routes: {_MEDIA} — GET /watch/:id"],
        grounded="deadbee",
        load_drift=lambda *a: [_synth_ref(_MEDIA, "ok")],
    )
    assert errors(report) == [], report.render("Grounding")
    assert any("still valid at @abc1234" in n for n in notes(report))


def test_moved_revision_route_citation_gone_is_tier2():
    report = run_synth(
        [f"- Routes: {_MEDIA} — GET /watch/:id/gone"],
        grounded="deadbee",
        load_drift=lambda *a: [_synth_ref(_MEDIA, "ok")],
    )
    assert tier2("deadbee", "abc1234") in errors(report)


def test_moved_revision_changed_page_section_warns_with_diff():
    report = run_synth(
        [f"- Pages: {_PAGES} — /admin"],
        grounded="deadbee",
        load_drift=lambda *a: [_synth_ref(_PAGES, "stale")],
    )
    assert errors(report) == []
    assert any(f"§{_PAGES} changed" in w for w in warnings(report))


def test_new_item_mixed_with_a_citation_on_one_line_is_an_error():
    report = run_synth(
        [
            f"- Routes: {_MEDIA} — GET /bogus, POST /media/fresh in "
            "apps/media/src/f.ts [NEW: tbd]"
        ]
    )
    msgs = errors(report)
    assert len(msgs) == 1, msgs
    assert "own sub-bullet" in msgs[0]


def test_new_item_on_its_own_sub_bullet_beside_a_citation_passes():
    report = run_synth(
        [
            "- Routes:",
            f"  - {_MEDIA} — GET /media/ping",
            "  - POST /media/fresh in apps/media/src/f.ts [NEW: tbd]",
        ]
    )
    assert errors(report) == [], report.render("Grounding")


@pytest.mark.parametrize(
    "line, bad",
    [
        (f"- Symbols: {_SYMS} — AdminController, Bogus", "symbol 'Bogus'"),
        (f"- Jobs: {_JOBS} — createPartition, bogus", "job 'bogus'"),
    ],
)
def test_every_listed_name_of_a_job_or_symbol_id_is_checked(line, bad):
    msgs = errors(run_synth([line]))
    assert len(msgs) == 1 and bad in msgs[0], msgs


def test_listed_names_with_backticks_and_commas_stay_whole():
    ok = run_synth([f"- Jobs: {_JOBS} — createPartition, `nightly cleanup`"])
    assert errors(ok) == [], ok.render("Grounding")


def test_files_new_entry_is_its_own_path():
    report = run_synth(
        ["- Files:", "  - apps/media/src/x.ts in apps/media/src/x.ts [NEW: tbd]"]
    )
    msgs = errors(report)
    assert len(msgs) == 1 and "a Files entry is its own path" in msgs[0], msgs
