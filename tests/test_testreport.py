from __future__ import annotations

from pathlib import Path

from strata_kb import testreport

STORY = "ST-1"
KIDS = ("ST-1.web", "ST-1.api")
REG_TC3 = "Run: yes\nFailed: ST-0/TC-3\nKnown: none"
REG_OK = "Run: yes\nFailed: none\nKnown: none\nsize 4, passed 4, failed 0"


def _report(
    *,
    verdict: str = "PASS",
    rows: str = "| AC1 | TC-01 | PASS | tests/ST-1/tc01.spec.ts | ![](assets/tc01.png) |",
    defects: str = "",
    rds: str = "",
    review: str = "| Q2 | 2 | pass |",
    extra: str = "",
    regression: str = REG_OK,
) -> str:
    return (
        "# R1 — ST-1 — Show airspace\n"
        f"> Story: {STORY} · Round: 1 · Verdict: {verdict}\n"
        "> Environment: staging · shop-fe abc1234 · shop-api def5678 · Date: 2026-11-14\n"
        "> Test cases: tests/ST-1/test-cases.md @ 1a2b3c4\n\n"
        "## Summary\n1/1 TCs, 0 defects, 0 regression defects\n\n"
        f"## Results by AC\n| AC | TC | Result | Script | Evidence |\n|---|---|---|---|---|\n{rows}\n\n"
        f"## Defects\n{defects}\n"
        f"## Regression\n{regression}\n\n"
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
    bad = _report(verdict="FAIL", defects=_d(1, reg="yes"), regression=REG_TC3)
    err = _errors(_lint(tmp_path, bad))
    assert "Broken TC" in err and "Baseline" in err and "Overlap" in err
    ok = _report(verdict="FAIL", defects=_d(1, reg="yes", more=YES), regression=REG_TC3)
    assert _lint(tmp_path, ok).passed
    r = testreport.parse(ok)
    assert r.defects[0].broken_tc == "ST-0 TC-3" and r.defects[0].regression
    nb = YES.replace("Baseline: R1 @ abc passed", "Baseline: no baseline")
    nb_report = _report(
        verdict="FAIL", defects=_d(1, reg="yes", more=nb), regression=REG_TC3
    )
    assert _lint(tmp_path, nb_report).passed


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
    ok = _report(rds=rd, rows="| AC1 | TC-01 | PASS | s | |", regression=REG_TC3)
    r = testreport.parse(ok)
    assert r.regression_defects[0].key == "ST-0/TC-3"
    assert _lint(tmp_path, ok).passed
    same = _report(rds=rd.replace("ST-0", STORY), regression=REG_TC3)
    assert "RD1" in _errors(_lint(tmp_path, same))


def test_dotenv_value_in_report_is_error_without_echoing_it(tmp_path):
    (tmp_path / ".env").write_text(
        "TEST_BUYER_PASSWORD=s3cretvalue!\nSHORT=abc\n", encoding="utf-8"
    )
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
    f.write_text(
        _report(verdict="FAIL", defects=_d(1, guilty="OTHER.web")), encoding="utf-8"
    )
    spec = tmp_path / "tests" / STORY
    spec.mkdir(parents=True)
    (spec / "test-cases.md").write_text(
        "> Story: ST-1 · Children: ST-1.web\n", encoding="utf-8"
    )
    args = ["report", "lint", str(f), "--repo-root", str(tmp_path)]
    res = CliRunner().invoke(app, [*args, "--json"])
    assert res.exit_code == 1 and json.loads(res.output)["pass"] is False
    f.write_text(
        _report(verdict="FAIL", defects=_d(1, guilty="ST-1.web")), encoding="utf-8"
    )
    res = CliRunner().invoke(app, args)
    assert res.exit_code == 0 and "REPORT: PASS" in res.output


# --- real template -----------------------------------------------------------

REVIEW6 = (
    "| Date | Round | Verdict | Reviewer | Coverage | Open gaps |\n"
    "|---|---|---|---|---|---|\n"
    "| 2026-11-14 | 2 | pass | senior-tester | complete | none |\n"
)


def _from_template(*, fail: bool) -> str:
    from strata_kb import initcmd

    t = initcmd.read_template("test-report-template.md")
    t = t.replace("R<n> — <story-id> — <story title>", "R1 — ST-1 — Show airspace")
    t = t.replace(
        "Story: <id> · Round: <n> · Verdict: PASS | FAIL",
        f"Story: ST-1 · Round: 1 · Verdict: {'FAIL' if fail else 'PASS'}",
    )
    t = t.replace(
        "Environment: <name> · <repo> <commit> · … · Date: YYYY-MM-DD",
        "Environment: staging · shop-fe abc1234 · Date: 2026-11-14",
    )
    t = t.replace(
        "tests/<story-id>/test-cases.md @ <tester commit>",
        "tests/ST-1/test-cases.md @ 1a2b3c4",
    )
    t = t.replace("tests/…/tc01.spec.ts", "tests/ST-1/tc01.spec.ts")
    t = t.replace("Run: yes | no (<reason>)", "Run: yes", 1)
    t = t.replace(
        "Failed: <closed story id>/TC-<k>, … | none",
        "Failed: ST-0/TC-3, ST-0/TC-4" if fail else "Failed: none",
    )
    t = t.replace("Known: <closed story id>/TC-<k>, … | none", "Known: none")
    if fail:
        t = t.replace(
            "<symptom>   Guilty: <child id>", "wrong level   Guilty: ST-1.web", 2
        )
        t = t.replace(
            "Broken TC: <closed story id> TC-<k> · Baseline: R<m> @ <commits> passed",
            "Broken TC: ST-0 TC-3 · Baseline: R1 @ abc1234 passed",
        )
        t = t.replace(
            "<page/route/service> ↔ <file> in <child PR>", "/airspace ↔ a.ts in PR 4"
        )
        t = t.replace(
            "<symptom>  Story: <closed story id> · TC-<k> ·",
            "old bug  Story: ST-0 · TC-4 ·",
        )
    else:
        a, b = t.index("### D1"), t.index("## Regression  ")
        t = t[:a] + t[b:]
        a, b = t.index("### RD1"), t.index("## Environment")
        t = t[:a] + t[b:]
    return t.rstrip("\n") + "\n" + REVIEW6


def test_real_template_pass_variant_lints_clean(tmp_path):
    rep = _lint(tmp_path, _from_template(fail=False))
    assert rep.passed, rep.render("REPORT")


def test_real_template_fail_variant_lints_clean(tmp_path):
    text = _from_template(fail=True)
    r = testreport.parse(text)
    assert [d.regression for d in r.defects] == [False, True]
    assert r.regression_defects[0].key == "ST-0/TC-4"
    rep = _lint(tmp_path, text)
    assert rep.passed, rep.render("REPORT")


def test_heading_note_after_one_space_still_matches(tmp_path):
    text = _report().replace(
        "## Regression defects\n", "## Regression defects one per failure:\n"
    )
    assert _lint(tmp_path, text).passed


def test_hex_secret_in_body_flagged_but_header_commit_is_not(tmp_path):
    h = "a1" * 32
    bad = _report(verdict="FAIL", defects=_d(1, more=f"token={h}\n"))
    assert "credential" in _errors(_lint(tmp_path, bad))
    sha = "ab12" * 10
    ok = _report().replace("shop-fe abc1234", f"shop-fe {sha}")
    assert _lint(tmp_path, ok).passed
    base = YES.replace("R1 @ abc passed", f"R1 @ {sha} passed")
    assert _lint(
        tmp_path,
        _report(
            verdict="FAIL", defects=_d(1, reg="yes", more=base), regression=REG_TC3
        ),
    ).passed


def _test_env(tmp_path):
    import yaml

    from strata_kb import testenv

    data = yaml.safe_load(
        (
            Path(testenv.__file__).parent / "templates/init/test-env.example.yaml"
        ).read_text(encoding="utf-8")
    )
    (tmp_path / ".kb").mkdir(exist_ok=True)
    (tmp_path / ".kb/test-env.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return data["db"]["url_env"]


def test_dotenv_scan_limited_to_vars_test_env_names(tmp_path):
    var = _test_env(tmp_path)
    (tmp_path / ".env").write_text(
        f"TEST_ENV_NAME=staging-eu\n{var}=dbvalue-12345\n", encoding="utf-8"
    )
    assert _lint(tmp_path, _report(extra="env staging-eu")).passed
    err = _errors(_lint(tmp_path, _report(extra="db dbvalue-12345")))
    assert var in err and "dbvalue" not in err


def test_no_results_rows_or_columns_is_error(tmp_path):
    empty = _report(rows="")
    assert "no result rows" in _errors(_lint(tmp_path, empty))
    nocol = _report().replace("| Result |", "| Outcome |")
    assert "columns" in _errors(_lint(tmp_path, nocol))


def test_children_fall_back_to_ticket_split_table(tmp_path):
    d = tmp_path / "tests" / STORY
    d.mkdir(parents=True)
    (d / "test-cases.md").write_text(
        "> Story: ST-1 · Children:  · Ticket revision: 1\n", encoding="utf-8"
    )
    from strata_kb import planparents

    (d / "ticket.md").write_text("ticket", encoding="utf-8")
    seen = []
    orig = planparents.children
    planparents.children = lambda text, pid: seen.append((text, pid)) or []
    try:
        testreport.story_children(d / "test-cases.md", STORY)
    finally:
        planparents.children = orig
    assert seen == [("ticket", STORY)]


# --- regression block contract (spec D6) -------------------------------------

GOLDEN = Path(__file__).parent / "data" / "tester_report_golden.md"


def _golden() -> str:
    return GOLDEN.read_text(encoding="utf-8")


def _three_rows() -> str:
    return "\n".join(
        f"| AC{k} | TC-0{k} | PASS | tests/ST-1/tc0{k}.spec.ts | |" for k in (1, 2, 3)
    )


def test_golden_report_parses_to_the_failed_and_known_keys():
    r = testreport.parse(_golden())
    assert r.regression_ran
    assert r.regression_failed == ("ST-0/TC-3", "ST-0/TC-4")
    assert r.known == ("ST-0/TC-5",)
    assert [d.regression for d in r.defects] == [True]
    assert r.regression_defects[0].key == "ST-0/TC-4"


def test_golden_report_lints_clean(tmp_path):
    rep = _lint(tmp_path, _golden())
    assert rep.passed, rep.render("REPORT")


def test_failed_keys_include_rd_and_regression_defect_keys():
    reg = "Run: yes\nFailed: none\nKnown: none"
    rd = "### RD1 — old   Story: ST-0 · TC-4 · S2 · P1\n\n"
    d = _d(
        1,
        reg="yes",
        more="Broken TC: ST-0 TC-3 · Baseline: no baseline\nOverlap: /a ↔ b\n",
    )
    r = testreport.parse(_report(verdict="FAIL", defects=d, rds=rd, regression=reg))
    assert set(r.regression_failed) == {"ST-0/TC-3", "ST-0/TC-4"}


def test_regression_ran_only_from_run_yes():
    for block, ran in (
        ("Run: yes\nFailed: none\nKnown: none", True),
        ("Run: no (story TCs failed)\nFailed: none\nKnown: none", False),
        ("size 4, passed 4, failed 0", False),
        ("", False),
    ):
        assert testreport.parse(_report(regression=block)).regression_ran is ran


def test_pass_report_needs_run_yes(tmp_path):
    no = "Run: no (skipped)\nFailed: none\nKnown: none"
    assert "Run: yes" in _errors(_lint(tmp_path, _report(regression=no)))
    assert "Run: yes" in _errors(_lint(tmp_path, _report(regression="")))
    fail = _report(
        verdict="FAIL",
        regression=no,
        defects=_d(1),
    )
    assert _lint(tmp_path, fail).passed


def test_rd_and_regression_defect_keys_must_be_listed_as_failed(tmp_path):
    rd = "### RD1 — old   Story: ST-0 · TC-3 · S2 · P1\n\n"
    assert "ST-0/TC-3" in _errors(_lint(tmp_path, _report(rds=rd)))
    ok = _report(rds=rd, regression=REG_TC3)
    assert _lint(tmp_path, ok).passed
    d = _d(1, reg="yes", more=YES)
    miss = _report(verdict="FAIL", defects=d)
    assert "ST-0/TC-3" in _errors(_lint(tmp_path, miss))


def test_malformed_regression_keys_are_errors(tmp_path):
    for line in ("Failed: ST-0 TC-3", "Failed: ST-0/TC-x", "Known: nothing"):
        label = line.split(":")[0]
        other = "Known: none" if label == "Failed" else "Failed: none"
        reg = f"Run: yes\n{line}\n{other}"
        assert "rep-regression" in [
            i.code for i in _lint(tmp_path, _report(regression=reg)).issues
        ], line


def test_every_spec_tc_needs_a_result_row(tmp_path):
    d = tmp_path / "reports" / STORY
    (d / "assets").mkdir(parents=True)
    (d / "assets/tc01.png").write_bytes(b"x")

    def lint(text, tcs):
        return testreport.lint(
            text, report_dir=d, story_children=KIDS, repo_root=tmp_path, spec_tcs=tcs
        )

    one_row = _report()  # a PASS report with only TC-01
    err = _errors(lint(one_row, ("TC-01", "TC-02", "TC-03")))
    assert "TC-02" in err and "TC-03" in err and "TC-01" not in err
    assert lint(one_row, ("TC-01",)).passed
    assert lint(_report(rows=_three_rows()), ("TC-01", "TC-02", "TC-03")).passed


def test_cli_report_lint_reads_tcs_from_the_spec(tmp_path):
    from typer.testing import CliRunner

    from strata_kb.cli import app

    d = tmp_path / "reports" / STORY
    (d / "assets").mkdir(parents=True)
    (d / "assets/tc01.png").write_bytes(b"x")
    (d / "R1.md").write_text(_report(), encoding="utf-8")
    spec = tmp_path / "tests" / STORY
    spec.mkdir(parents=True)
    (spec / "test-cases.md").write_text(
        "> Story: ST-1 · Children: ST-1.web\n\n## TC-01 — a\n\n## TC-02 — b\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(
        app, ["report", "lint", str(d / "R1.md"), "--repo-root", str(tmp_path)]
    )
    assert res.exit_code == 1 and "TC-02" in res.output


def test_cli_report_lint_story_header_must_match_its_folder(tmp_path):
    from typer.testing import CliRunner

    from strata_kb.cli import app

    d = tmp_path / "reports" / "ST-2"
    (d / "assets").mkdir(parents=True)
    (d / "assets/tc01.png").write_bytes(b"x")
    (d / "R1.md").write_text(_report(), encoding="utf-8")  # header says ST-1
    res = CliRunner().invoke(
        app, ["report", "lint", str(d / "R1.md"), "--repo-root", str(tmp_path)]
    )
    assert res.exit_code == 1
    assert "does not match its folder" in res.output and "ST-2" in res.output
