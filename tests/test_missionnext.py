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
