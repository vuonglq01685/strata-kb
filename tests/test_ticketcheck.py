"""Engine tests for `kb ticket check` (`ticketcheck.check`).

Hermetic: the -code document is a REAL `demo-code` produced by
`codeingest.core.run()` over `tests/fixtures_coderepo.build_code_repo`, so
every id, column, route, command and tree path asserted here is what the
extractors actually emit (see the spec's §1 table). No hub, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import models, ticketcheck
from strata_kb.codeingest import core
from strata_kb.lintcore import LintReport
from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def code_doc(tmp_path: Path, run_git) -> tuple[Path, str]:
    """(kb_dir, revision) for a freshly ingested `demo-code`."""
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    kb_dir = tmp_path / "kb"
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"
        )
    )
    manifest = models.load_yaml_model(
        kb_dir / "demo-code" / "_manifest.yaml", models.Manifest
    )
    return kb_dir, manifest.revision


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


def ticket(section: str | None) -> str:
    parts = ["# T-1 — Show airspace", "", "## Summary", "Something.", ""]
    if section is not None:
        parts += ["## Technical grounding", section, ""]
    parts += ["## Open questions", "- [ ] none", ""]
    return "\n".join(parts)


def run(text: str, kb_dir: Path) -> LintReport:
    def load_doc(repo, doc):
        d = kb_dir / doc
        if not (d / "_manifest.yaml").exists():
            return None
        return ticketcheck.load_doc_dir(d, str(d))

    return ticketcheck.check(text, load_doc=load_doc)


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


def test_long_revision_prefix_matches(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev + "0" * (40 - len(rev)))), kb_dir)
    assert not any("stale grounding" in e for e in errors(report))


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
