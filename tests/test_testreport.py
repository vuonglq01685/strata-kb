from __future__ import annotations

from pathlib import Path

from strata_kb import testreport

STORY = "ST-1"
KIDS = ("ST-1.web", "ST-1.api")


def _report(
    *,
    verdict: str = "PASS",
    rows: str = "| AC1 | TC-01 | PASS | tests/ST-1/tc01.spec.ts | ![](assets/tc01.png) |",
    defects: str = "",
    rds: str = "",
    review: str = "| Q2 | 2 | pass |",
    extra: str = "",
) -> str:
    return (
        "# R1 — ST-1 — Show airspace\n"
        f"> Story: {STORY} · Round: 1 · Verdict: {verdict}\n"
        "> Environment: staging · shop-fe abc1234 · shop-api def5678 · Date: 2026-11-14\n"
        "> Test cases: tests/ST-1/test-cases.md @ 1a2b3c4\n\n"
        "## Summary\n1/1 TCs, 0 defects, 0 regression defects\n\n"
        f"## Results by AC\n| AC | TC | Result | Script | Evidence |\n|---|---|---|---|---|\n{rows}\n\n"
        f"## Defects\n{defects}\n"
        "## Regression\nsize 4, passed 4, failed 0\n\n"
        f"## Regression defects\n{rds}\n"
        f"## Environment & data seeds\nstaging, seed a. {extra}\n\n"
        f"## Review record\n| Review | Round | Verdict |\n|---|---|---|\n{review}\n"
    )


def _d(n: int, guilty: str = "ST-1.web", reg: str = "no", more: str = "") -> str:
    return (
        f"### D{n} — wrong level   Guilty: {guilty} · Regression: {reg} · S2 · P1\n"
        f"{more}Steps to reproduce: open\n\n"
    )


YES = "Broken TC: ST-0 TC-3 · Baseline: R1 @ abc passed\nOverlap: /a ↔ a.ts in PR 1\n"


def _lint(tmp_path: Path, text: str, kids=KIDS):
    d = tmp_path / "reports" / STORY
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "assets/tc01.png").write_bytes(b"x")
    return testreport.lint(text, report_dir=d, story_children=kids, repo_root=tmp_path)


def _errors(rep) -> str:
    return "\n".join(i.message for i in rep.issues if i.level == "error")


def test_pass_report_parses_and_lints_clean(tmp_path):
    text = _report()
    r = testreport.parse(text)
    assert (r.story, r.round, r.verdict, r.env_name) == (STORY, 1, "PASS", "staging")
    assert r.commits == {"shop-fe": "abc1234", "shop-api": "def5678"}
    assert r.date == "2026-11-14"
    assert r.results == (("AC1", "TC-01", "PASS"),)
    assert r.review_passed and not r.defects
    rep = _lint(tmp_path, text)
    assert rep.passed, rep.render("REPORT")


def test_fail_row_with_pass_verdict_is_error(tmp_path):
    rows = "| AC1 | TC-01 | FAIL | tests/ST-1/tc01.spec.ts | |"
    assert "verdict" in _errors(_lint(tmp_path, _report(rows=rows))).lower()


def test_defect_with_pass_verdict_is_error(tmp_path):
    assert "verdict" in _errors(_lint(tmp_path, _report(defects=_d(1)))).lower()


def test_fail_verdict_without_failure_is_error(tmp_path):
    assert "verdict" in _errors(_lint(tmp_path, _report(verdict="FAIL"))).lower()


def test_incomplete_verdict_is_refused(tmp_path):
    assert "verdict" in _errors(_lint(tmp_path, _report(verdict="INCOMPLETE"))).lower()


def test_regression_yes_defect_needs_baseline_and_overlap(tmp_path):
    bad = _report(verdict="FAIL", defects=_d(1, reg="yes"))
    err = _errors(_lint(tmp_path, bad))
    assert "Broken TC" in err and "Baseline" in err and "Overlap" in err
    ok = _report(verdict="FAIL", defects=_d(1, reg="yes", more=YES))
    assert _lint(tmp_path, ok).passed
    r = testreport.parse(ok)
    assert r.defects[0].broken_tc == "ST-0 TC-3" and r.defects[0].regression
    nb = YES.replace("Baseline: R1 @ abc passed", "Baseline: no baseline")
    assert _lint(
        tmp_path, _report(verdict="FAIL", defects=_d(1, reg="yes", more=nb))
    ).passed


def test_defect_without_regression_flag_is_error(tmp_path):
    d = "### D1 — x   Guilty: ST-1.web · S2\n"
    assert "Regression" in _errors(_lint(tmp_path, _report(verdict="FAIL", defects=d)))


def test_guilty_child_must_belong_to_story(tmp_path):
    t = _report(verdict="FAIL", defects=_d(1, guilty="OTHER.web"))
    assert "OTHER.web" in _errors(_lint(tmp_path, t))
    assert _lint(
        tmp_path, _report(verdict="FAIL", defects=_d(1, guilty=STORY)), ()
    ).passed


def test_regression_defect_must_name_other_story(tmp_path):
    rd = "### RD1 — old   Story: ST-0 · TC-3 · S2 · P1\n\n"
    ok = _report(rds=rd, rows="| AC1 | TC-01 | PASS | s | |")
    r = testreport.parse(ok)
    assert r.regression_defects[0].key == "ST-0/TC-3"
    assert _lint(tmp_path, ok).passed
    same = _report(rds=rd.replace("ST-0", STORY))
    assert "RD1" in _errors(_lint(tmp_path, same))


def test_regression_failed_and_known_parse():
    text = _report().replace(
        "size 4, passed 4, failed 0",
        "size 4, passed 2, failed 2\nFailed: ST-0/TC-3, ST-0/TC-4\nknown: ST-0/TC-4",
    )
    r = testreport.parse(text)
    assert r.regression_ran
    assert r.regression_failed == ("ST-0/TC-3", "ST-0/TC-4")
    assert r.known == ("ST-0/TC-4",)


def test_dotenv_value_in_report_is_error_without_echoing_it(tmp_path):
    (tmp_path / ".env").write_text("TEST_BUYER_PASSWORD=s3cretvalue!\nSHORT=abc\n")
    rep = _lint(tmp_path, _report(extra="logged in with s3cretvalue!"))
    err = _errors(rep)
    assert "TEST_BUYER_PASSWORD" in err and "s3cretvalue" not in err


def test_credential_shape_in_report_is_error(tmp_path):
    rep = _lint(tmp_path, _report(extra="url postgres://u:pw@h/db"))
    assert "credential" in _errors(rep) and "pw@" not in _errors(rep)


def test_image_outside_assets_is_error(tmp_path):
    rows = "| AC1 | TC-01 | PASS | s | ![](shots/a.png) |"
    assert "assets/" in _errors(_lint(tmp_path, _report(rows=rows)))


def test_review_not_passed_is_error(tmp_path):
    for review in ("| Q2 | 2 | blocked |", ""):
        assert "Q2 has not passed" in _errors(_lint(tmp_path, _report(review=review)))


def test_cli_report_lint_json(tmp_path):
    import json

    from typer.testing import CliRunner

    from strata_kb.cli import app

    d = tmp_path / "reports" / STORY
    (d / "assets").mkdir(parents=True)
    (d / "assets/tc01.png").write_bytes(b"x")
    f = d / "R1.md"
    f.write_text(_report(verdict="FAIL", defects=_d(1, guilty="OTHER.web")))
    spec = tmp_path / "tests" / STORY
    spec.mkdir(parents=True)
    (spec / "test-cases.md").write_text("> Story: ST-1 · Children: ST-1.web\n")
    args = ["report", "lint", str(f), "--repo-root", str(tmp_path)]
    res = CliRunner().invoke(app, [*args, "--json"])
    assert res.exit_code == 1 and json.loads(res.output)["pass"] is False
    f.write_text(_report(verdict="FAIL", defects=_d(1, guilty="ST-1.web")))
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 0 and "REPORT: PASS" in res.output
