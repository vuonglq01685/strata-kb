"""`testflow` — derived test status, known failures, duplicate tester repos."""

from __future__ import annotations

from pathlib import Path

from strata_kb import models, planingest, planstatus, testflow, ticketclaim
from strata_kb.hub import HubHandle
from tests.conftest import make_fed_entry
from tests.test_missionlint import MISSION_ID
from tests.test_testreport import REG_OK, _d, _report

STORY = f"{MISSION_ID}-US2"  # the published ticket of the `plan_hub` plan
KIDS = (f"{STORY}.web", f"{STORY}.api")


def _text(
    story: str,
    n: int,
    verdict: str = "PASS",
    *,
    guilty: str = "",
    date: str = "2026-11-14",
    regression: str = REG_OK,
    rds: str = "",
) -> str:
    text = _report(
        verdict=verdict,
        defects=_d(1, guilty) if guilty else "",
        rds=rds,
        regression=regression,
        rows=f"| AC1 | TC-01 | {'PASS' if verdict == 'PASS' else 'FAIL'} | a.ts | |",
    )
    return (
        text.replace("ST-1", story)
        .replace("Round: 1", f"Round: {n}")
        .replace("# R1", f"# R{n}")
        .replace("2026-11-14", date)
    )


def publish_tests(hub: Path, repo: str, story: str, *reports: str) -> None:
    """A `<repo>-test` document as `kb report-ingest` writes it: one group per
    story, L3 headings demoted and the H1 dropped."""
    doc = f"{repo}-test"
    entry = make_fed_entry(
        hub / "federation",
        repo,
        doc,
        title=f"{repo} — tests",
        tags=["test", "generated"],
    )
    l3 = ""
    sections = []
    for text in reports:
        n = testflow.testreport.parse(text).round
        title = planingest.section_title(text)
        l3 += f"## {story}.R{n} {title}\n\n{planingest.l3_body(text)}\n\n"
        sections.append(
            models.SectionEntry(
                id=f"{story}.R{n}",
                title=title,
                summary=f"R{n}",
                status="summarized",
                file=story,
            )
        )
    folder = entry / doc
    (folder / "ch1.md").unlink()
    (folder / "ch1.raw.md").unlink()
    (folder / f"{story}.md").write_text(l3, encoding="utf-8")
    (folder / f"{story}.raw.md").write_text(l3, encoding="utf-8")
    manifest = models.load_yaml_model(folder / "_manifest.yaml", models.Manifest)
    models.save_yaml_model(
        folder / "_manifest.yaml", manifest.model_copy(update={"sections": sections})
    )


def _statuses(hub: HubHandle) -> dict[str, tuple[str, str]]:
    repos, _ = planstatus.hub_plans(hub)
    rows = [s for r in repos for m in r.missions for s in m.stories]
    return {s.us_id: (s.status, s.test_status) for s in rows}


def _facts(**kw) -> testflow.TestFacts:
    return testflow.TestFacts(**kw)


def _rep(story: str, n: int, verdict: str = "PASS", **kw):
    return testflow.testreport.parse(_text(story, n, verdict, **kw))


def test_pass_report_closes_story_and_children():
    facts = _facts(reports={STORY: (_rep(STORY, 1),)})
    assert testflow.story_test_status(STORY, KIDS, facts) == dict.fromkeys(
        (STORY, *KIDS), "closed"
    )


def test_fail_reopens_only_guilty_child():
    facts = _facts(reports={STORY: (_rep(STORY, 1, "FAIL", guilty=KIDS[0]),)})
    assert testflow.story_test_status(STORY, KIDS, facts) == {
        STORY: "reopened",
        KIDS[0]: "reopened",
    }


def test_fix_round_in_history_gives_fix_done():
    facts = _facts(
        reports={STORY: (_rep(STORY, 1, "FAIL", guilty=KIDS[0]),)},
        fix_rounds={KIDS[0]: frozenset({1})},
    )
    assert testflow.story_test_status(STORY, KIDS, facts)[KIDS[0]] == "fix-done"
    stale = _facts(
        reports=facts.reports,
        fix_rounds={KIDS[0]: frozenset({2})},  # answers another round
    )
    assert testflow.story_test_status(STORY, KIDS, stale)[KIDS[0]] == "reopened"


def test_held_tester_claim_gives_testing(plan_hub):
    store = ticketclaim.ClaimStore(ticketclaim.claims_db_path(plan_hub.root))
    store.take("ba-one", STORY, "tester-1", role="tester")
    assert _statuses(plan_hub)[STORY] == ("ready", "testing")
    assert testflow.story_test_status(STORY, (), _facts()) == {}


def test_closed_is_final_even_if_revision_bumps(plan_hub):
    publish_tests(plan_hub.root, "qa-repo", STORY, _text(STORY, 1))
    before = _statuses(plan_hub)[STORY]
    ticket = next(plan_hub.federation_dir.glob("ba-one/ba-one-plan/*.raw.md"))
    ticket.write_text(
        ticket.read_text(encoding="utf-8").replace("> Revision: 1", "> Revision: 2"),
        encoding="utf-8",
    )
    assert _statuses(plan_hub)[STORY] == before == ("ready", "closed")


def test_status_field_never_changes(plan_hub):
    done = next(s for s in _statuses(plan_hub) if _statuses(plan_hub)[s][0] == "done")
    publish_tests(plan_hub.root, "qa-repo", done, _text(done, 1))
    assert _statuses(plan_hub)[done] == ("done", "closed")


def test_report_for_unknown_story_is_ignored(plan_hub):
    before = _statuses(plan_hub)
    publish_tests(plan_hub.root, "qa-repo", "NOPE-US9", _text("NOPE-US9", 1))
    assert _statuses(plan_hub) == before


def test_unreadable_report_is_skipped(plan_hub):
    publish_tests(plan_hub.root, "qa-repo", STORY, _text(STORY, 1))
    raw = plan_hub.federation_dir / "qa-repo" / "qa-repo-test" / f"{STORY}.raw.md"
    raw.write_text("no sections here", encoding="utf-8")
    assert testflow.load_facts(plan_hub).reports == {}


def test_missing_claims_db_means_no_testing(plan_hub):
    assert testflow.load_facts(plan_hub).testing == frozenset()
    assert not ticketclaim.claims_db_path(plan_hub.root).exists()


def _failed(*keys: str, known: tuple[str, ...] = ()) -> str:
    failed = ", ".join(keys) or "none"
    return f"Run: yes\nFailed: {failed}\nKnown: {', '.join(known) or 'none'}"


def test_known_failure_dedupes_and_closes():
    rd = "### RD1 — old bug  Story: ST-0 · TC-3 ·\n"
    a = _rep(
        "ST-A",
        1,
        "FAIL",
        date="2026-11-10",
        regression=_failed("ST-0/TC-3"),
        rds=rd,
    )
    b = _rep("ST-B", 1, "FAIL", date="2026-11-11", regression=_failed("ST-0/TC-3"))
    facts = _facts(reports={"ST-A": (a,), "ST-B": (b,)})
    known = testflow.known_failures(facts)
    assert known["ST-0/TC-3"].story == "ST-A"
    assert known["ST-0/TC-3"].duplicates == ("ST-B R1",)

    later = _rep("ST-C", 1, date="2026-11-12")  # regression ran, nothing failed
    facts = _facts(reports={"ST-A": (a,), "ST-B": (b,), "ST-C": (later,)})
    assert testflow.known_failures(facts) == {}


def test_two_tester_repos_for_one_ba_repo_is_doctor_error(plan_hub):
    publish_tests(plan_hub.root, "qa-one", STORY, _text(STORY, 1))
    assert testflow.duplicate_testers(plan_hub, testflow.load_facts(plan_hub)) == []
    publish_tests(plan_hub.root, "qa-two", STORY, _text(STORY, 2))
    msgs = testflow.duplicate_testers(plan_hub, testflow.load_facts(plan_hub))
    assert len(msgs) == 1 and "ba-one" in msgs[0]
    assert "qa-one" in msgs[0] and "qa-two" in msgs[0]

    from strata_kb.doctor.checks import hub as hub_checks

    issues = hub_checks.duplicate_tester_issues(plan_hub)
    assert [i.level for i in issues] == ["error"]


def test_fix_rounds_read_from_history_refs():
    from strata_kb import missionnext

    hist = (
        "| Ticket | Title | Domain refs |\n| --- | --- | --- |\n"
        "| A.web | t | svc.x, fix:R2 |\n| A.api | t | |\n| B | t | fix:R1, fix:R3 |\n"
    )
    assert missionnext.fix_rounds_from_history(hist) == {
        "A.web": frozenset({2}),
        "B": frozenset({1, 3}),
    }


def test_render_shows_test_status_after_status():
    from strata_kb import missionnext

    row = missionnext.StoryStatus("US1", "M", "t", "done", (), test_status="closed")
    assert "| done / closed |" in missionnext.render([row], [])


def test_claim_read_honours_ttl_env_and_never_writes(plan_hub, monkeypatch):
    import sqlite3
    from datetime import UTC, datetime, timedelta

    db = ticketclaim.claims_db_path(plan_hub.root)
    old = datetime.now(UTC) - timedelta(hours=10)
    ticketclaim.ClaimStore(db, now=lambda: old).take(
        "ba-one", STORY, "tester-1", role="tester"
    )
    snapshot = (db.stat().st_mtime_ns, db.read_bytes())
    monkeypatch.setenv("STRATA_KB_CLAIM_TTL", str(48 * 3600))
    assert testflow.load_facts(plan_hub).testing == {STORY}
    assert (db.stat().st_mtime_ns, db.read_bytes()) == snapshot
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT closed_at FROM claims").fetchall() == [(None,)]
    monkeypatch.setenv("STRATA_KB_CLAIM_TTL", "3600")  # now it is unheld ...
    assert testflow.load_facts(plan_hub).testing == frozenset()
    assert (db.stat().st_mtime_ns, db.read_bytes()) == snapshot  # ... yet not closed


def test_unsplit_story_reaches_fix_done():
    rep = _rep(STORY, 1, "FAIL", guilty=STORY)
    facts = _facts(reports={STORY: (rep,)}, fix_rounds={STORY: frozenset({1})})
    assert testflow.story_test_status(STORY, (), facts) == {STORY: "fix-done"}
    assert testflow.story_test_status(STORY, (), _facts(reports=facts.reports)) == {
        STORY: "reopened"
    }


def test_unsafe_group_file_name_is_skipped(plan_hub):
    publish_tests(plan_hub.root, "qa-repo", STORY, _text(STORY, 1))
    manifest = plan_hub.federation_dir / "qa-repo" / "qa-repo-test" / "_manifest.yaml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(f"file: {STORY}", "file: ../../x"),
        encoding="utf-8",
    )
    assert testflow.load_facts(plan_hub).reports == {}


def test_doctor_reports_duplicate_testers_only_for_hub_and_tester(git_kb, plan_hub):
    from strata_kb import doctor

    publish_tests(plan_hub.root, "qa-one", STORY, _text(STORY, 1))
    publish_tests(plan_hub.root, "qa-two", STORY, _text(STORY, 2))
    kb = git_kb["kb"]

    def errors(kind: str) -> list[str]:
        (kb / "config.yaml").write_text(
            f"kind: {kind}\nrepo_id: demo\n", encoding="utf-8"
        )
        res = doctor.run(kb, plan_hub)
        return [i.message for i in res.issues if "tester repo" in i.message]

    assert errors("ba") == [] and errors("dev") == []
    assert len(errors("tester")) == 1


def test_rd_and_regression_defect_keys_open_known_failures():
    rd = "### RD1 — old bug   Story: ST-0 · TC-4 · S2 · P1\n\n"
    rep = _rep("ST-A", 1, rds=rd, regression=_failed(), date="2026-11-10")
    assert testflow.known_failures(_facts(reports={"ST-A": (rep,)})) == {
        "ST-0/TC-4": testflow.KnownFailure("ST-0/TC-4", "ST-A", 1, "RD1")
    }


def test_round_that_skipped_regression_closes_nothing():
    a = _rep(
        "ST-A",
        1,
        "FAIL",
        guilty="ST-A.web",
        regression=_failed("ST-0/TC-3"),
        date="2026-11-10",
    )
    skipped = _rep(
        "ST-B",
        1,
        "FAIL",
        guilty="ST-B.web",
        date="2026-11-11",
        regression="Run: no (story TCs failed)\nFailed: none\nKnown: none",
    )
    facts = _facts(reports={"ST-A": (a,), "ST-B": (skipped,)})
    assert list(testflow.known_failures(facts)) == ["ST-0/TC-3"]


def test_known_listing_keeps_the_key_open_and_counts_a_duplicate():
    a = _rep("ST-A", 1, regression=_failed("ST-0/TC-3"), date="2026-11-10")
    b = _rep("ST-B", 1, regression=_failed(known=("ST-0/TC-3",)), date="2026-11-11")
    known = testflow.known_failures(_facts(reports={"ST-A": (a,), "ST-B": (b,)}))
    assert known["ST-0/TC-3"].duplicates == ("ST-B R1",)


# --- golden report: skill output -> report-ingest -> hub -> known failures ----


def _publish_ingested(hub: Path, tmp_path: Path, report: str) -> testflow.TestFacts:
    """Run `kb report-ingest` on a tester repo holding `report` and copy the
    generated `shop-test` document into the hub as a federation entry."""
    import shutil

    from tests.test_testingest import run_tests, write_repo

    root = tmp_path / "tester"
    root.mkdir()
    write_repo(root, report=report)
    assert run_tests(root).skipped == []
    entry = make_fed_entry(
        hub / "federation", "shop", "shop-test", title="shop — tests",
        tags=["test", "generated"],
    )  # fmt: skip
    shutil.rmtree(entry / "shop-test")
    shutil.copytree(root / "kb" / "shop-test", entry / "shop-test")
    return testflow.load_facts(HubHandle(root=hub))


def test_golden_report_end_to_end_opens_dedupes_and_closes(plan_hub, tmp_path):
    from tests.test_testreport import _golden

    facts = _publish_ingested(plan_hub.root, tmp_path, _golden())
    (rep,) = facts.reports["ST-1"]
    assert rep.regression_failed == ("ST-0/TC-3", "ST-0/TC-4")
    assert rep.known == ("ST-0/TC-5",)
    open_ = testflow.known_failures(facts)
    assert set(open_) == {"ST-0/TC-3", "ST-0/TC-4"}
    assert open_["ST-0/TC-4"].rd_id == "RD1" and open_["ST-0/TC-4"].story == "ST-1"

    other = _rep("ST-9", 1, regression=_failed("ST-0/TC-4"), date="2026-11-15")
    dup = testflow.known_failures(
        _facts(reports={"ST-1": facts.reports["ST-1"], "ST-9": (other,)})
    )
    assert dup["ST-0/TC-4"].duplicates == ("ST-9 R1",)
    assert "ST-0/TC-3" not in dup  # ST-9 ran the suite and TC-3 passed

    clean = _rep("ST-9", 1, date="2026-11-15")  # regression ran, nothing failed
    closed = testflow.known_failures(
        _facts(reports={"ST-1": facts.reports["ST-1"], "ST-9": (clean,)})
    )
    assert closed == {}

    skipped = _rep(
        "ST-9", 1, "FAIL", guilty="ST-9.web", date="2026-11-15",
        regression="Run: no (story TCs failed)\nFailed: none\nKnown: none",
    )  # fmt: skip
    kept = testflow.known_failures(
        _facts(reports={"ST-1": facts.reports["ST-1"], "ST-9": (skipped,)})
    )
    assert set(kept) == {"ST-0/TC-3", "ST-0/TC-4"}


def test_closed_is_final_when_a_later_round_fails():
    facts = _facts(
        reports={
            STORY: (_rep(STORY, 1), _rep(STORY, 2, "FAIL", guilty=KIDS[0])),
        },
        fix_rounds={KIDS[0]: frozenset({2})},
        testing=frozenset({STORY}),
    )
    assert testflow.story_test_status(STORY, KIDS, facts) == dict.fromkeys(
        (STORY, *KIDS), "closed"
    )


def test_overlay_of_a_closed_story_shows_the_closing_round(plan_hub):
    publish_tests(
        plan_hub.root,
        "qa-repo",
        STORY,
        _text(STORY, 1),
        _text(STORY, 2, "FAIL", guilty=f"{STORY}.web", date="2026-11-15"),
    )
    repos, _ = planstatus.hub_plans(plan_hub)
    row = next(
        s for r in repos for m in r.missions for s in m.stories if s.us_id == STORY
    )
    assert (row.test_status, row.test_round) == ("closed", 1)
