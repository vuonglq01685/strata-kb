"""Engine tests for `kb mission next` (`strata_kb.missionnext`). Text in,
statuses out — no filesystem, no hub."""

from __future__ import annotations

from strata_kb import missionnext

PLATFORM = """# Platform operations
> Mission: M-platform

## US backlog
| US ID | Title |
|---|---|
| M-platform-US1 | Foundation slice |
| M-platform-US2 | Observability |
| M-platform-US3 | Backups |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-platform-US1 | none | L | first |
| M-platform-US2 | US1 | M | bare id |

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.api [arch §3.2] | DECIDED | lead | M-platform-US1 |
| D2 | New svc.metrics | OPEN | Alice | M-platform-US2 |

## Services & order
- Grounded on: myflix:myflix-code @ abc1234
"""

CATALOG = """# Catalog
> Mission: M-catalog

## US backlog
| US ID | Title |
|---|---|
| M-catalog-US1 | Browse titles |
| M-catalog-US2 | Search |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-catalog-US2 | M-catalog-US1, M-platform-US2 | M | cross-mission |
| M-catalog-US1 | M-platform-US1 | S | after foundation |
"""


def test_dep_ids_full_bare_and_none():
    assert missionnext.dep_ids("none", "M-a") == ()
    assert missionnext.dep_ids("-", "M-a") == ()
    assert missionnext.dep_ids("", "M-a") == ()
    assert missionnext.dep_ids("US1", "M-a") == ("M-a-US1",)
    assert missionnext.dep_ids("M-b-US3, US2", "M-a") == ("M-b-US3", "M-a-US2")
    assert missionnext.dep_ids("M-b-US3 and M-b-US3", "M-a") == ("M-b-US3",)
    assert missionnext.dep_ids("after US10 lands (see notes)", "M-a") == ("M-a-US10",)


def test_parse_mission_reads_backlog_sequencing_and_decisions():
    mission_id, stories, decisions = missionnext.parse_mission(PLATFORM)
    assert mission_id == "M-platform"
    assert [s.us_id for s in stories] == ["M-platform-US1", "M-platform-US2", "M-platform-US3"]
    assert stories[0].title == "Foundation slice"
    assert stories[0].depends_on == ()
    assert stories[0].seq_index == 0
    assert stories[1].depends_on == ("M-platform-US1",)
    assert stories[1].seq_index == 1
    assert stories[2].depends_on == ()
    assert stories[2].seq_index is None
    assert decisions.rows["D2"].blocks == ("M-platform-US2",)


def test_parse_mission_without_sequencing_or_decisions():
    text = "# X\n> Mission: M-x\n\n## US backlog\n| US ID | Title |\n|---|---|\n| M-x-US1 | Only |\n"
    mission_id, stories, decisions = missionnext.parse_mission(text)
    assert mission_id == "M-x"
    assert stories == [missionnext.Story("M-x-US1", "M-x", "Only", (), None)]
    assert decisions.rows == {}


def test_parse_mission_without_id_or_backlog():
    mission_id, stories, _ = missionnext.parse_mission("# nothing here\n")
    assert mission_id is None
    assert stories == []


def test_grounded_repo_id():
    assert missionnext.grounded_repo_id(PLATFORM) == "myflix"
    assert missionnext.grounded_repo_id(CATALOG) is None
    assert missionnext.grounded_repo_id("- Grounded on: demo-code @ abc1234\n") is None


HISTORY = """# myflix-svc

> Ticket history, appended by `kb svc note`. Do not edit by hand.

## hist.api api — ticket history

| Ticket | Title | Domain refs |
| --- | --- | --- |
| M-platform-US1 | Foundation slice | arch §3 |

## hist.web web — ticket history

| Ticket | Title | Domain refs |
|:---|:---:|---:|
| M-catalog-US1 | Browse titles | |
| M-platform-US1 | Foundation slice | arch §3 |
"""


def test_done_ids_from_history_reads_every_hist_section():
    assert missionnext.done_ids_from_history(HISTORY) == {"M-platform-US1", "M-catalog-US1"}


def test_done_ids_from_history_handles_missing_text():
    assert missionnext.done_ids_from_history(None) == set()
    assert missionnext.done_ids_from_history("") == set()


def _run(drafted=(), done=None):
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    return {
        s.us_id: s
        for s in missionnext.statuses(parsed, set(drafted), None if done is None else set(done))
    }


def test_first_story_with_decided_row_is_ready():
    s = _run()["M-platform-US1"]
    assert s.status == "ready" and s.reasons == ()


def test_dependency_not_done_blocks_even_when_drafted():
    by = _run(drafted=["M-platform-US1"])
    assert by["M-platform-US1"].status == "drafted"
    assert by["M-platform-US2"].status == "blocked"
    assert by["M-platform-US2"].reasons == (
        "US M-platform-US1 not done",
        "D2 OPEN (owner: Alice)",
    )


def test_done_dependency_and_decided_rows_make_ready():
    by = _run(drafted=["M-platform-US1"], done=["M-platform-US1"])
    assert by["M-platform-US1"].status == "done"
    assert by["M-catalog-US1"].status == "ready"
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: Alice)",)


def test_cross_mission_dependency_and_order():
    order = [s.us_id for s in missionnext.statuses(
        [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)], set(), set()
    )]
    assert order == [
        "M-platform-US1", "M-platform-US2", "M-platform-US3",   # US3 absent from Sequencing → last
        "M-catalog-US2", "M-catalog-US1",                       # Sequencing row order, not backlog
    ]
    by = _run(done=["M-platform-US1", "M-catalog-US1"])
    assert by["M-catalog-US2"].status == "blocked"
    assert by["M-catalog-US2"].reasons == ("US M-platform-US2 not done",)


def test_unknown_dependency_is_named():
    text = CATALOG.replace("M-platform-US1", "M-ghost-US9")
    parsed = [missionnext.parse_mission(text)]
    by = {s.us_id: s for s in missionnext.statuses(parsed, set(), set())}
    assert by["M-catalog-US1"].reasons == ("US M-ghost-US9 unknown",)


def test_no_done_information_never_marks_done():
    by = _run(drafted=["M-platform-US1"], done=None)
    assert by["M-platform-US1"].status == "drafted"
    assert by["M-catalog-US1"].status == "blocked"
    assert by["M-catalog-US1"].reasons == ("US M-platform-US1 not done",)


def test_decision_with_empty_status_and_owner_prints_placeholders():
    text = PLATFORM.replace("| D2 | New svc.metrics | OPEN | Alice |", "| D2 | New svc.metrics |  |  |")
    by = {s.us_id: s for s in missionnext.statuses([missionnext.parse_mission(text)], set(), {"M-platform-US1"})}
    assert by["M-platform-US2"].reasons == ("D2 OPEN (owner: ?)",)


def test_render_table_and_next_line():
    parsed = [missionnext.parse_mission(PLATFORM), missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-platform-US1"}, {"M-platform-US1"})
    text = missionnext.render(results, [])
    lines = text.splitlines()
    assert lines[0] == "| US | Mission | Status | Reason |"
    assert lines[1] == "|---|---|---|---|"
    assert "| M-platform-US1 | M-platform | done |  |" in lines
    assert "| M-platform-US2 | M-platform | blocked | D2 OPEN (owner: Alice) |" in lines
    assert "| M-catalog-US2 | M-catalog | blocked | US M-catalog-US1 not done; US M-platform-US2 not done |" in lines
    # M-platform-US3 has no dependency and no D-row, so it is the first ready
    # story in output order (before any M-catalog story).
    assert lines[-1] == "Next: M-platform-US3 — Backups"
    assert lines[-2] == ""


def test_render_notes_come_first_and_none_ready_counts():
    parsed = [missionnext.parse_mission(CATALOG)]
    results = missionnext.statuses(parsed, {"M-catalog-US1"}, None)
    text = missionnext.render(results, ["done: unknown (no repo id — pass --repo-id)"])
    lines = text.splitlines()
    assert lines[0] == "note: done: unknown (no repo id — pass --repo-id)"
    assert lines[1] == ""
    assert lines[2] == "| US | Mission | Status | Reason |"
    assert lines[-1] == "Next: none ready — 1 blocked, 1 drafted, 0 done"


def test_to_json_shape():
    parsed = [missionnext.parse_mission(PLATFORM)]
    results = missionnext.statuses(parsed, set(), set())
    data = missionnext.to_json(results, ["n1"])
    assert set(data) == {"notes", "stories", "next"}
    assert data["notes"] == ["n1"]
    assert data["next"] == "M-platform-US1"
    assert data["stories"][0] == {
        "us_id": "M-platform-US1", "mission_id": "M-platform", "title": "Foundation slice",
        "status": "ready", "reasons": [],
    }
    assert data["stories"][1]["reasons"] == ["US M-platform-US1 not done", "D2 OPEN (owner: Alice)"]
    assert missionnext.to_json([], [])["next"] is None
