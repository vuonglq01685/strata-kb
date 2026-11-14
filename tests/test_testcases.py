from __future__ import annotations

from pathlib import Path

from strata_kb import testcases
from tests.test_ticketlint import _build_ticket, golden_block  # noqa: F401

STORY = "ST-1"
FLOW = "Airspace record missing"


def _ticket(golden_block: str, *, flows: tuple[str, ...] = ()) -> str:  # noqa: F811
    uc = "### Main flow\nDispatcher opens it.\n### Alternate / exception flows\n"
    uc += "".join(f"- {f}\n" for f in flows)
    return _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1 — Given an airspace, when opened, then designation shows\n"
                "- [ ] AC2 — Given a level, when above 100, then it is shown"
            ),
            "## Use cases": uc,
        },
    )


def _case(n: int, polarity: str, script: str = "tc{n}.spec.ts") -> str:
    script = script.format(n=f"{n:02d}")
    return (
        f"## TC-{n:02d} — case {n}\n| Field | Value |\n|---|---|\n"
        "| Objective | Verify it |\n| Type | UI |\n| Priority | P1 |\n"
        f"| Technique | EP |\n| Polarity | {polarity} |\n| Preconditions | none |\n"
        "| Test data | seed a |\n| Steps | 1. open |\n| Expected result | shown |\n"
        f"| Script | tests/{STORY}/{script} |\n| Automation | automated |\n\n"
    )


def _spec(
    *,
    revision: int = 1,
    trace: str = "| AC1 | TC-01 |\n| AC2 | TC-02, TC-03 |",
    cases: str | None = None,
    flows: str = "",
) -> str:
    if cases is None:
        cases = _case(1, "positive") + _case(2, "positive") + _case(3, "boundary")
    return (
        f"# Test cases — {STORY} — Show airspace\n"
        f"> Story: {STORY} · Children: {STORY}.web · Ticket revision: {revision}\n\n"
        f"## Scope & traceability\n| AC | Test cases |\n|---|---|\n{trace}\n\n"
        f"{flows}{cases}## Change log\n## Review record\n"
    )


def _dir(tmp_path: Path, *names: str) -> Path:
    d = tmp_path / "tests" / STORY
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_text("// t")
    return d


def _errs(rep) -> list[str]:
    return [i.message for i in rep.issues if i.level == "error"]


def test_clean_spec_passes(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    rep = testcases.lint(_spec(), _ticket(golden_block), spec_dir=d)
    assert _errs(rep) == []
    assert rep.passed
    spec = testcases.parse(_spec())
    assert spec.children == (f"{STORY}.web",)
    assert spec.trace["AC2"] == ("TC-02", "TC-03")
    assert spec.cases[0].fields["Script"] == f"tests/{STORY}/tc01.spec.ts"


def test_ac_without_positive_tc_is_error(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    cases = _case(1, "positive") + _case(2, "negative") + _case(3, "boundary")
    rep = testcases.lint(_spec(cases=cases), _ticket(golden_block), spec_dir=d)
    assert any("AC2" in e and "positive" in e for e in _errs(rep))
    rep = testcases.lint(
        _spec(trace="| AC1 | TC-01 |"), _ticket(golden_block), spec_dir=d
    )
    assert any("AC2" in e for e in _errs(rep))


def test_tc_citing_unknown_ac_is_error(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    spec = _spec(trace="| AC1 | TC-01 |\n| AC2 | TC-02, TC-03 |\n| AC9 | TC-01 |")
    assert any(
        "AC9" in e
        for e in _errs(testcases.lint(spec, _ticket(golden_block), spec_dir=d))
    )


def test_alternate_flow_without_tc_is_error(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    ticket = _ticket(golden_block, flows=(FLOW,))
    rep = testcases.lint(_spec(), ticket, spec_dir=d)
    assert any(FLOW in e for e in _errs(rep))
    covered = f"## Alternate flows coverage\n| Flow | Test cases |\n|---|---|\n| {FLOW} | TC-03 |\n\n"
    rep = testcases.lint(_spec(flows=covered), ticket, spec_dir=d)
    assert _errs(rep) == []


def test_orphan_script_and_missing_script_are_errors(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "extra.spec.ts")
    rep = testcases.lint(_spec(), _ticket(golden_block), spec_dir=d)
    errs = _errs(rep)
    assert any("tc03.spec.ts" in e for e in errs)
    assert any("extra.spec.ts" in e for e in errs)


def test_script_outside_spec_dir_is_error(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts")
    cases = (
        _case(1, "positive") + _case(2, "positive") + _case(3, "boundary", "../x.ts")
    )
    rep = testcases.lint(_spec(cases=cases), _ticket(golden_block), spec_dir=d)
    assert any("TC-03" in e for e in _errs(rep))


def test_revision_mismatch_is_error(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    rep = testcases.lint(_spec(revision=2), _ticket(golden_block), spec_dir=d)
    assert any("revision" in e.lower() for e in _errs(rep))


def test_digit_ac_without_boundary_is_warning(tmp_path, golden_block):  # noqa: F811
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    cases = _case(1, "positive") + _case(2, "positive") + _case(3, "positive")
    rep = testcases.lint(_spec(cases=cases), _ticket(golden_block), spec_dir=d)
    assert rep.passed
    assert any(i.level == "warning" and "AC2" in i.message for i in rep.issues)


def test_placeholders_and_missing_field_are_errors(tmp_path):
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    spec = _spec().replace("| Steps | 1. open |", "| Steps | … |")
    spec = spec.replace("| Expected result | shown |\n", "", 1)
    errs = _errs(testcases.lint(spec, None, spec_dir=d))
    assert any("Steps" in e for e in errs)
    assert any("Expected result" in e for e in errs)


def test_no_ticket_skips_ticket_checks(tmp_path):
    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    rep = testcases.lint(_spec(revision=9, trace="| AC7 | TC-01 |"), None, spec_dir=d)
    assert not any("AC" in e or "revision" in e.lower() for e in _errs(rep))


def test_missing_heading_is_error(tmp_path):
    d = _dir(tmp_path)
    rep = testcases.lint(_spec().replace("## Change log\n", ""), None, spec_dir=d)
    assert any("## Change log" in e for e in _errs(rep))


def test_cli_lint_local_ticket(tmp_path, golden_block, monkeypatch):  # noqa: F811
    from typer.testing import CliRunner

    from strata_kb.cli import app

    d = _dir(tmp_path, "tc01.spec.ts", "tc02.spec.ts", "tc03.spec.ts")
    (d / "ticket.md").write_text(_ticket(golden_block))
    spec = tmp_path / "spec.md"
    spec.write_text(_spec())
    monkeypatch.chdir(tmp_path)
    res = CliRunner().invoke(app, ["testcase", "lint", str(spec)])
    assert res.exit_code == 0, res.output
    assert "TC: PASS" in res.output
    spec.write_text(_spec(revision=5))
    res = CliRunner().invoke(app, ["testcase", "lint", str(spec), "--json"])
    assert res.exit_code == 1
