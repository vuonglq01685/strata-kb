"""Tests for the mission template contract (`mission.py`) and the
`PARENT_MISSION_RE` back-link it adds to `ticket.py` — Task 2 of the BA
mission-plan work.

As shipped here the module under test is pure: plain regex/constant
assertions against literal strings, no fixtures, no filesystem, no
network, no LLM. Later tasks build `missionlint.py` (the DoR lint engine)
on top of these constants and will append hub-backed tests to this file
that exercise the `fed_hub` git fixture (from conftest.py) and a golden
mission pinning/citing published docs — none of that exists yet.
"""

from __future__ import annotations

from center_kb import lintcore, mission, ticket


def test_required_headings_are_the_agreed_contract():
    assert mission.REQUIRED_MISSION_HEADINGS == (
        "## Summary",
        "## Business goal",
        "## Scope",
        "## System context (C4 L1)",
        "## Containers (C4 L2)",
        "## Constraints & assumptions",
        "## US backlog",
        "## KB context",
        "## Definition of Ready",
    )


def test_component_heading_is_not_required():
    assert mission.COMPONENT_HEADING not in mission.REQUIRED_MISSION_HEADINGS


def test_diagram_keywords_accept_c4_and_flowchart():
    assert mission.L1_KEYWORDS == ("C4Context", "flowchart")
    assert mission.L2_KEYWORDS == ("C4Container", "flowchart")
    assert mission.L3_KEYWORDS == ("C4Component", "flowchart")


def test_mission_id_format():
    assert mission.MISSION_ID_RE.match("M-airspace-filter")
    assert mission.MISSION_ID_RE.match("M-a1")
    assert not mission.MISSION_ID_RE.match("airspace-filter")  # no M- prefix
    assert not mission.MISSION_ID_RE.match("M-Airspace")  # not lowercase
    assert not mission.MISSION_ID_RE.match("M-air_space")  # not kebab


def test_mission_line_extracts_the_id():
    text = "# Title\n\n> Mission: M-airspace-filter\n"
    assert mission.MISSION_LINE_RE.search(text).group(1) == "M-airspace-filter"


def test_mission_line_rejects_missing_marker():
    """Without the leading '>' the line is prose, not the mission marker."""
    text = "# Title\n\nMission: M-airspace-filter\n"
    assert mission.MISSION_LINE_RE.search(text) is None


def test_us_id_is_derived_from_the_mission_id():
    pattern = mission.us_id_re("M-airspace-filter")
    assert pattern.match("M-airspace-filter-US1")
    assert pattern.match("M-airspace-filter-US42")
    assert not pattern.match("M-other-US1")  # wrong mission
    assert not pattern.match("M-airspace-filter-US0")  # 1-based
    assert not pattern.match("M-airspace-filter-1")  # missing 'US'


# The literal '## US backlog' table from the design doc (spec §4.3),
# reused verbatim across the three constants below so a Task 3
# implementer testing against this file sees the same fixture the spec
# shows: header row, separator row, and one data row.
_BACKLOG_HEADER = "| US ID | Title |"
_BACKLOG_SEP = "|---|---|"
_BACKLOG_ROW = "| M-airspace-filter-US1 | Render restrictive airspace polygons |"


def test_backlog_header_re_matches_only_the_exact_header():
    assert mission.BACKLOG_HEADER_RE.match(_BACKLOG_HEADER)
    assert not mission.BACKLOG_HEADER_RE.match(_BACKLOG_ROW)
    assert not mission.BACKLOG_HEADER_RE.match("| Story | Name |")  # wrong column names


def test_backlog_sep_re_matches_only_the_separator_row():
    assert mission.BACKLOG_SEP_RE.match(_BACKLOG_SEP)
    assert not mission.BACKLOG_SEP_RE.match(_BACKLOG_ROW)


def test_backlog_row_re_extracts_id_and_title_from_a_data_row():
    m = mission.BACKLOG_ROW_RE.match(_BACKLOG_ROW)
    assert m.group(1) == "M-airspace-filter-US1"
    assert m.group(2) == "Render restrictive airspace polygons"


def test_backlog_row_re_also_matches_header_and_separator_rows():
    """BACKLOG_ROW_RE is NOT self-discriminating: it happily matches the
    header ('US ID' / 'Title') and the separator ('---' / '---') as if
    they were data rows. A caller that runs this regex over every line of
    the '## US backlog' section without first locating the header row
    positionally, and skipping the separator row that follows it, will
    misreport '---' and 'US ID' as malformed US ids on a perfectly valid
    table. Callers MUST locate the header positionally and skip the
    separator row — never rely on this regex alone to tell a data row
    from a header/separator row."""
    header_match = mission.BACKLOG_ROW_RE.match(_BACKLOG_HEADER)
    assert header_match.group(1) == "US ID"
    assert header_match.group(2) == "Title"

    sep_match = mission.BACKLOG_ROW_RE.match(_BACKLOG_SEP)
    assert sep_match.group(1) == "---"
    assert sep_match.group(2) == "---"


def test_placeholder_matches_the_design_docs_convention():
    assert mission.PLACEHOLDER == "%%TODO: verify against codebase%%"


def test_parent_mission_line_extracts_the_id():
    text = "# Ticket title\n\n> Parent mission: M-airspace-filter\n"
    assert (
        ticket.PARENT_MISSION_RE.search(text).group(1) == "M-airspace-filter"
    )


def test_parent_mission_line_rejects_missing_marker():
    """Without the leading '>' the line is prose, not the back-link."""
    text = "# Ticket title\n\nParent mission: M-airspace-filter\n"
    assert ticket.PARENT_MISSION_RE.search(text) is None


def test_parent_mission_line_rejects_capitalized_mission():
    """The regex is case-sensitive on 'mission' (lowercase 'm'). A BA who
    writes '> Parent Mission:' with a capital M gets no match — and
    because the back-link check is opt-in on the line's presence, that
    typo silently disables check 10 for this ticket instead of raising a
    lint error. This test pins that sharp edge rather than papering over
    it with re.I."""
    text = "# Ticket title\n\n> Parent Mission: M-airspace-filter\n"
    assert ticket.PARENT_MISSION_RE.search(text) is None


def test_required_ticket_headings_are_unchanged():
    """REQUIRED_HEADINGS is a compatibility contract across the BA's local
    install, the shared MCP server, and CI — Phase 4.1 must not touch it,
    or every provisioned BA repo needs a migration."""
    assert ticket.REQUIRED_HEADINGS == (
        "## Summary",
        "## User Story",
        "## Background / Business context",
        "## Acceptance Criteria",
        "## Use cases",
        "## Sequence diagram",
        "## Business flow",
        "## KB context",
        "## Definition of Ready",
    )


from pathlib import Path

import pytest

from center_kb import kbcontext, missionlint
from center_kb.hub import HubHandle

MISSION_ID = "M-airspace-filter"
DEFAULT_TITLE = "# Filter and display controlled airspace"
MISSION_LINE = f"> Mission: {MISSION_ID}"

REFS = ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"]

# Template order: required + recommended sections as in mission-template.md
# ('## Technology decisions' and NFR after C4 L2; Sequencing and Open
# questions after the backlog).
ALL_MISSION_HEADINGS = (
    "## Summary",
    "## Business goal",
    "## Scope",
    "## System context (C4 L1)",
    "## Containers (C4 L2)",
    "## Technology decisions",
    "## Non-functional requirements",
    "## Constraints & assumptions",
    "## US backlog",
    "## Sequencing",
    "## Open questions",
    "## KB context",
    "## Definition of Ready",
)


def _hub(fed_hub: Path) -> HubHandle:
    return HubHandle(root=fed_hub)


@pytest.fixture
def golden_block(fed_hub: Path) -> str:
    block, warning = kbcontext.build_context_block(
        _hub(fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return block


def _default_sections(block: str) -> dict[str, str]:
    return {
        "## Summary": (
            "Dispatchers need controlled airspace shown on the planning map."
        ),
        "## Business goal": (
            "Cut route-briefing time by showing restrictive airspace inline. "
            "Airspace records follow arinc-kb:arinc-424 §5.3."
        ),
        "## Scope": (
            "**In scope:** map rendering, filtering by airspace class.\n"
            "**Out of scope:** editing airspace data, NOTAM ingestion."
        ),
        "## System context (C4 L1)": (
            "```mermaid\n"
            "C4Context\n"
            "  Person(dispatcher, \"Dispatcher\")\n"
            "  System(planner, \"Flight Planner\")\n"
            "  Rel(dispatcher, planner, \"Plans routes with\")\n"
            "```"
        ),
        "## Containers (C4 L2)": (
            "```mermaid\n"
            "C4Container\n"
            "  Container(spa, \"Map UI\", \"TypeScript\")\n"
            "  Container(api, \"Airspace API\", \"Python\")\n"
            "  Rel(spa, api, \"Reads airspace from\", \"HTTPS\")\n"
            "```"
        ),
        "## Constraints & assumptions": (
            "ICAO designation rules per icao-kb:icao-annex-2 §1.1 apply."
        ),
        "## US backlog": (
            "| US ID | Title |\n"
            "|---|---|\n"
            f"| {MISSION_ID}-US1 | Render restrictive airspace polygons |\n"
            f"| {MISSION_ID}-US2 | Filter airspace by class |"
        ),
        "## Technology decisions": (
            "| # | Decision | Status | Owner | Blocks |\n"
            "|---|---|---|---|---|\n"
            "| D1 | Map rendering library | DECIDED | tech-lead | "
            f"{MISSION_ID}-US1 |"
        ),
        "## Non-functional requirements": (
            "| Concern | Target | How to measure | Source |\n"
            "|---|---|---|---|\n"
            "| Map load | First render under 3 s with 500 polygons | "
            "Grafana p95 dashboard | team SLA |"
        ),
        "## Sequencing": (
            "| US ID | Depends on | Size | Notes |\n"
            "|---|---|---|---|\n"
            f"| {MISSION_ID}-US1 | None | M | Foundation |\n"
            f"| {MISSION_ID}-US2 | {MISSION_ID}-US1 | S | |"
        ),
        "## Open questions": (
            "- [ ] Q1 — Confirm map tile provider quota — "
            "owner: tech-lead — impact: cost — blocks: "
            f"{MISSION_ID}-US1"
        ),
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": (
            "- [ ] Business goal, scope, L1 + L2 diagrams, backlog present\n"
            "- [ ] Every citation resolves at the pinned version\n"
            "- [ ] Backlog reviewed with the team"
        ),
    }


def _build_mission(
    block: str,
    *,
    skip: str | None = None,
    title: str = DEFAULT_TITLE,
    mission_line: str = MISSION_LINE,
    overrides: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> str:
    sections = _default_sections(block)
    if overrides:
        sections.update(overrides)
    parts = [title, "", mission_line, ""]
    for heading in ALL_MISSION_HEADINGS:
        if heading == skip:
            continue
        parts.append(heading)
        parts.append(sections[heading])
        parts.append("")
    for heading, body in (extra or {}).items():
        parts.append(heading)
        parts.append(body)
        parts.append("")
    return "\n".join(parts)


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


# --- check 1: title + mission id ---


def test_mission_id_extracted_from_body(golden_block: str):
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), None
    )
    assert issues == []
    assert mission_id == MISSION_ID
    assert any("filename" in n for n in notes)


def test_missing_mission_line_errors(golden_block: str):
    text = _build_mission(golden_block, mission_line="")
    issues, _notes, mission_id = missionlint.check_mission_id(text, None)
    assert mission_id is None
    assert any("> Mission:" in i.message for i in issues)


def test_malformed_mission_id_errors(golden_block: str):
    text = _build_mission(golden_block, mission_line="> Mission: airspace")
    issues, _notes, mission_id = missionlint.check_mission_id(text, None)
    assert mission_id is None
    assert any("M-<slug>" in i.message for i in issues)


def test_filename_mismatch_errors(golden_block: str, tmp_path: Path):
    path = tmp_path / "M-wrong-name.md"
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), path
    )
    assert mission_id == MISSION_ID
    assert notes == []
    assert any("M-wrong-name" in i.message for i in issues)


def test_filename_match_is_clean(golden_block: str, tmp_path: Path):
    path = tmp_path / f"{MISSION_ID}.md"
    issues, notes, mission_id = missionlint.check_mission_id(
        _build_mission(golden_block), path
    )
    assert issues == []
    assert notes == []
    assert mission_id == MISSION_ID


# --- check 6/7: backlog table ---


def test_backlog_parses(golden_block: str):
    issues, us_ids = missionlint.check_backlog(
        _build_mission(golden_block), MISSION_ID
    )
    assert issues == []
    assert us_ids == [f"{MISSION_ID}-US1", f"{MISSION_ID}-US2"]


def test_backlog_missing_header_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| Story | Name |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | Render polygons |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert us_ids == []
    assert any("| US ID | Title |" in i.message for i in issues)


def test_backlog_with_no_rows_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={"## US backlog": "| US ID | Title |\n|---|---|"},
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert us_ids == []
    assert any("at least 1" in i.message for i in issues)


def test_backlog_bad_us_id_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                "| M-other-mission-US1 | Wrong mission |"
            )
        },
    )
    issues, _us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert any("M-other-mission-US1" in i.message for i in issues)


def test_backlog_duplicate_us_id_errors(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | First |\n"
                f"| {MISSION_ID}-US1 | Duplicate |"
            )
        },
    )
    issues, _us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert any("duplicate" in i.message.lower() for i in issues)


def test_backlog_row_above_header_errors(golden_block: str):
    """A BACKLOG_ROW_RE-matching row placed above the header must not be
    silently discarded — it would vanish from `us_ids` with no error, no
    warning, no note, which is the worst failure mode for a check whose
    output feeds Task 4's coverage gate."""
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                f"| {MISSION_ID}-US9 | Stray row above the header |\n"
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | Render restrictive airspace polygons |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert us_ids == [f"{MISSION_ID}-US1"]
    assert any(
        f"{MISSION_ID}-US9" in i.message and "above" in i.message
        for i in issues
    )


def test_backlog_prose_above_header_is_legal(golden_block: str):
    """Leading prose above the table (not a BACKLOG_ROW_RE match) must stay
    legal — only rows shaped like table rows are flagged."""
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "Stories below are ordered by priority.\n"
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | Render restrictive airspace polygons |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert issues == []
    assert us_ids == [f"{MISSION_ID}-US1"]


def test_backlog_missing_separator_errors(golden_block: str):
    """A header row with no separator row underneath does not render as a
    markdown table for the human reviewing the DoR — this must be an
    error, not silently accepted."""
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                f"| {MISSION_ID}-US1 | Render restrictive airspace polygons |"
            )
        },
    )
    issues, _us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert any("separator" in i.message.lower() for i in issues)


def test_backlog_numbering_gaps_are_allowed(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                f"| {MISSION_ID}-US1 | First |\n"
                f"| {MISSION_ID}-US7 | Seventh, after US2-US6 were dropped |"
            )
        },
    )
    issues, us_ids = missionlint.check_backlog(text, MISSION_ID)
    assert issues == []
    assert us_ids == [f"{MISSION_ID}-US1", f"{MISSION_ID}-US7"]


# --- check 13: placeholders ---


def test_placeholder_warns(golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## Constraints & assumptions": (
                "Service name %%TODO: verify against codebase%% unknown."
            )
        },
    )
    issues = missionlint.check_placeholders(text)
    assert len(issues) == 1
    assert issues[0].level == "warning"


def test_no_placeholder_is_silent(golden_block: str):
    assert missionlint.check_placeholders(_build_mission(golden_block)) == []


def test_multiple_placeholders_aggregate_into_one_issue(golden_block: str):
    """A single test with exactly one placeholder can't distinguish
    aggregation from one-issue-per-occurrence. Pin the count with two."""
    text = _build_mission(
        golden_block,
        overrides={
            "## Constraints & assumptions": (
                "Service name %%TODO: verify against codebase%% unknown, "
                "and so is the %%TODO: verify against codebase%% owner team."
            )
        },
    )
    issues = missionlint.check_placeholders(text)
    assert len(issues) == 1
    assert "2" in issues[0].message


# --- golden missions ---


def test_golden_mission_passes(fed_hub: Path, golden_block: str, tmp_path: Path):
    path = tmp_path / f"{MISSION_ID}.md"
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    (tickets / f"{MISSION_ID}-US1.md").write_text("x", encoding="utf-8")
    (tickets / f"{MISSION_ID}-US2.md").write_text("x", encoding="utf-8")

    report = missionlint.lint(
        _build_mission(golden_block),
        _hub(fed_hub),
        path=path,
        tickets_dir=tickets,
    )

    assert report.passed is True
    assert report.issues == []
    assert report.notes == []


def test_vietnamese_golden_mission_passes(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        title="# Lọc và hiển thị vùng trời có kiểm soát",
        overrides={
            "## Summary": (
                "Điều phối viên cần thấy vùng trời có kiểm soát trên bản đồ."
            ),
            "## Business goal": (
                "Giảm thời gian briefing tuyến bay. Bản ghi vùng trời theo "
                "arinc-kb:arinc-424 §5.3."
            ),
            "## Constraints & assumptions": (
                "Quy tắc định danh ICAO theo icao-kb:icao-annex-2 §1.1."
            ),
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is True
    assert _errors(report) == []


def test_flowchart_fallback_passes(fed_hub: Path, golden_block: str):
    """Mermaid documents C4 as experimental; teams whose renderer lacks C4
    support fall back to flowchart without failing DoR."""
    text = _build_mission(
        golden_block,
        overrides={
            "## System context (C4 L1)": (
                "```mermaid\n"
                "flowchart TD\n"
                "  D[Dispatcher] --> P[Flight Planner]\n"
                "```"
            ),
            "## Containers (C4 L2)": (
                "```mermaid\n"
                "flowchart LR\n"
                "  UI[Map UI] --> API[Airspace API]\n"
                "```"
            ),
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is True


def test_mermaid_init_directive_before_the_type_passes(
    fed_hub: Path, golden_block: str
):
    text = _build_mission(
        golden_block,
        overrides={
            "## System context (C4 L1)": (
                "```mermaid\n"
                "%%{init: {'theme':'neutral'}}%%\n"
                "C4Context\n"
                "  Person(d, \"Dispatcher\")\n"
                "```"
            ),
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is True


# --- check 2: required headings ---


@pytest.mark.parametrize("heading", mission.REQUIRED_MISSION_HEADINGS)
def test_missing_heading_errors(fed_hub: Path, golden_block: str, heading: str):
    text = _build_mission(golden_block, skip=heading)
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any(heading in msg for msg in _errors(report))


def test_heading_inside_a_fence_is_reported_missing(
    fed_hub: Path, golden_block: str
):
    """A required heading quoted inside a fenced code block — e.g. a BA
    pasting a reference mission or `TEMPLATE.md` into their own document as
    a worked example — must not satisfy the presence check. Regression
    test for the fence-aware `lintcore.check_headings` fix (shared with
    `kb ticket lint`)."""
    text = _build_mission(golden_block)
    fenced = text.replace(
        "## Business goal\n", "```markdown\n## Business goal\n```\n", 1
    )
    assert fenced != text  # sanity: the replace actually matched

    report = missionlint.lint(fenced, _hub(fed_hub))

    assert report.passed is False
    assert any(
        "missing required heading: '## Business goal'" in m
        for m in _errors(report)
    )


def test_missing_title_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(golden_block, title="Not a title line")
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("title" in msg.lower() for msg in _errors(report))


# --- checks 3/4/5: diagrams ---


def test_missing_l1_diagram_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={"## System context (C4 L1)": "No diagram here."},
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert any("C4 L1" in msg for msg in _errors(report))


def test_missing_l2_diagram_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={"## Containers (C4 L2)": "No diagram here."},
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert any("C4 L2" in msg for msg in _errors(report))


def test_wrong_keyword_in_l1_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## System context (C4 L1)": (
                "```mermaid\nsequenceDiagram\n  A->>B: hi\n```"
            )
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert any("C4 L1" in msg for msg in _errors(report))


def test_absent_l3_section_is_silent(fed_hub: Path, golden_block: str):
    report = missionlint.lint(_build_mission(golden_block), _hub(fed_hub))
    assert not any("C4 L3" in msg for msg in _errors(report))


def test_present_but_empty_l3_section_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        extra={mission.COMPONENT_HEADING: "Components go here, eventually."},
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert any("C4 L3" in msg for msg in _errors(report))


def test_valid_l3_section_passes(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        extra={
            mission.COMPONENT_HEADING: (
                "```mermaid\n"
                "C4Component\n"
                "  Component(h, \"Airspace handler\", \"Python\")\n"
                "```"
            )
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is True


# --- check 8: kb-context parses ---


def test_malformed_kb_context_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={"## KB context": "```yaml\nkb-context:\n  refs: [\n```"},
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is False


# --- check 10/11: citation consistency ---


def test_uncited_pinned_ref_warns(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## Constraints & assumptions": "No citation in this section."
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert any("icao-annex-2" in msg for msg in _warnings(report))


def test_inline_citation_not_pinned_errors(fed_hub: Path, golden_block: str):
    text = _build_mission(
        golden_block,
        overrides={
            "## Scope": (
                "**In scope:** map rendering per faa-kb:faa-7110 §2.2.\n"
                "**Out of scope:** editing."
            )
        },
    )
    report = missionlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("faa-7110" in msg for msg in _errors(report))


# --- check 12: coverage ---


def test_coverage_warns_for_undrafted_stories(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    (tickets / f"{MISSION_ID}-US1.md").write_text("x", encoding="utf-8")

    report = missionlint.lint(
        _build_mission(golden_block), _hub(fed_hub), tickets_dir=tickets
    )

    assert report.passed is True  # coverage is never an error
    assert any("1/2" in msg for msg in _warnings(report))
    assert any(f"{MISSION_ID}-US2" in msg for msg in _warnings(report))


def test_zero_coverage_at_creation_time_still_passes(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """A mission is written BEFORE its tickets exist. 0/N must never fail."""
    tickets = tmp_path / "tickets"
    tickets.mkdir()

    report = missionlint.lint(
        _build_mission(golden_block), _hub(fed_hub), tickets_dir=tickets
    )

    assert report.passed is True
    assert any("0/2" in msg for msg in _warnings(report))


def test_coverage_skipped_without_tickets_dir_emits_a_note(
    fed_hub: Path, golden_block: str
):
    report = missionlint.lint(_build_mission(golden_block), _hub(fed_hub))
    assert any("coverage" in n for n in report.notes)
    assert not any("/2" in msg for msg in _warnings(report))


def test_coverage_skipped_when_the_backlog_has_errors(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """A broken backlog leaves invalid entries in us_ids, so running
    coverage over it would demand a ticket file for garbage. Skipping is
    visible; filtering to the valid subset would silently shrink what
    coverage checked."""
    tickets = tmp_path / "tickets"
    tickets.mkdir()
    text = _build_mission(
        golden_block,
        overrides={
            "## US backlog": (
                "| US ID | Title |\n"
                "|---|---|\n"
                "| M-other-mission-US1 | Wrong mission |"
            )
        },
    )

    report = missionlint.lint(text, _hub(fed_hub), tickets_dir=tickets)

    assert report.passed is False
    assert any("backlog has errors" in n for n in report.notes)
    assert not any("US drafted" in msg for msg in _warnings(report))


def test_missing_hub_errors(golden_block: str):
    report = missionlint.lint(_build_mission(golden_block), None)
    assert report.passed is False
    assert any("hub" in msg for msg in _errors(report))


# --- template sync: the shipped template must satisfy its own contract ---


def _template_text() -> str:
    from importlib import resources

    return (
        resources.files("center_kb.templates.init")
        .joinpath("mission-template.md")
        .read_text(encoding="utf-8")
    )


def test_shipped_template_contains_every_required_heading():
    """Verify every required heading appears as a standalone line in the
    shipped template, using the exact set-membership idiom production
    `check_headings` uses (`{line.strip() for line in text.splitlines()}`)
    — so this test and the production gate compute "present" the same way
    and can never silently disagree.

    Neither this test nor `check_headings` is fence-aware: a heading that
    drifted inside a fenced code block would satisfy both equally. That is
    a real, shared blind spot, but closing it is a behavioural change to a
    shipped gate and belongs in `check_headings`, not in this test."""
    text = _template_text()
    present = {line.strip() for line in text.splitlines()}
    for heading in mission.REQUIRED_MISSION_HEADINGS:
        assert heading in present, f"template is missing {heading}"


def test_shipped_template_carries_both_required_diagrams():
    """The template ships C4-native fences. Assert the diagram checks
    directly rather than running full lint: the template is a fill-in form
    whose id and refs are angle-bracket placeholders, so the id and
    kb-context checks are expected to fail on it."""
    text = _template_text()
    assert (
        lintcore.check_diagram(
            text, "## System context (C4 L1)", mission.L1_KEYWORDS
        )
        == []
    ), "template L1 fence does not satisfy the L1 diagram check"
    assert (
        lintcore.check_diagram(
            text, "## Containers (C4 L2)", mission.L2_KEYWORDS
        )
        == []
    )


def test_shipped_template_backlog_table_has_the_exact_header():
    text = _template_text()
    body = lintcore.section_body(text, "## US backlog")
    assert body is not None
    assert any(
        mission.BACKLOG_HEADER_RE.match(line.strip())
        for line in body.splitlines()
    )


# --- new-template warnings (BA upgrade v2) ---


def test_golden_mission_emits_no_new_warnings(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    report = missionlint.lint(
        _build_mission(golden_block), _hub(fed_hub)
    )
    assert report.passed is True
    assert _warnings(report) == []


def test_c4_todo_without_decision_row_warns(
    fed_hub: Path, golden_block: str
):
    l2 = (
        "```mermaid\n"
        "C4Container\n"
        "  Container(api, \"Airspace API — "
        "%%TODO: verify against codebase%%\", \"Python\")\n"
        "```"
    )
    doc = _build_mission(
        golden_block,
        overrides={
            "## Containers (C4 L2)": l2,
            "## Technology decisions": (
                "| # | Decision | Status | Owner | Blocks |\n"
                "|---|---|---|---|---|"
            ),
        },
    )
    report = missionlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "every placeholder needs an owned decision row" in w
        for w in _warnings(report)
    )


def test_c4_todo_with_owned_decision_row_is_clean(
    fed_hub: Path, golden_block: str
):
    l2 = (
        "```mermaid\n"
        "C4Container\n"
        "  Container(api, \"Airspace API — "
        "%%TODO: verify against codebase%%\", \"Python\")\n"
        "```"
    )
    doc = _build_mission(
        golden_block,
        overrides={
            "## Containers (C4 L2)": l2,
            "## Technology decisions": (
                "| # | Decision | Status | Owner | Blocks |\n"
                "|---|---|---|---|---|\n"
                "| D1 | Airspace API stack | OPEN | tech-lead | "
                f"{MISSION_ID}-US1 |"
            ),
        },
    )
    report = missionlint.lint(doc, _hub(fed_hub))
    assert not any(
        "decision row" in w for w in _warnings(report)
    )
    # The pre-existing placeholder-count warning still fires — additive.
    assert any("unresolved" in w for w in _warnings(report))


def test_ownerless_decision_row_warns(fed_hub: Path, golden_block: str):
    doc = _build_mission(
        golden_block,
        overrides={
            "## Technology decisions": (
                "| # | Decision | Status | Owner | Blocks |\n"
                "|---|---|---|---|---|\n"
                f"| D1 | Storage engine | OPEN | <who> | {MISSION_ID}-US1 |"
            ),
        },
    )
    report = missionlint.lint(doc, _hub(fed_hub))
    assert any(
        "has no owner" in w for w in _warnings(report)
    )


def test_sequencing_not_covering_backlog_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_mission(
        golden_block,
        overrides={
            "## Sequencing": (
                "| US ID | Depends on | Size | Notes |\n"
                "|---|---|---|---|\n"
                f"| {MISSION_ID}-US1 | None | M | |"
            ),
        },
    )
    report = missionlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        f"'## Sequencing' does not cover: {MISSION_ID}-US2" in w
        for w in _warnings(report)
    )


def test_missing_recommended_mission_section_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_mission(golden_block, skip="## Sequencing")
    report = missionlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "recommended section missing: '## Sequencing'" in w
        for w in _warnings(report)
    )


def test_ownerless_mission_open_question_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_mission(
        golden_block,
        overrides={"## Open questions": "- [ ] Q1 — unowned question"},
    )
    report = missionlint.lint(doc, _hub(fed_hub))
    assert any("no 'owner:'" in w for w in _warnings(report))


def test_legacy_mission_still_passes(fed_hub: Path, golden_block: str):
    """A pre-upgrade mission (only required sections) keeps DoR: PASS."""
    sections = _default_sections(golden_block)
    parts = [DEFAULT_TITLE, "", MISSION_LINE, ""]
    for heading in mission.REQUIRED_MISSION_HEADINGS:
        parts.append(heading)
        parts.append(sections[heading])
        parts.append("")
    report = missionlint.lint("\n".join(parts), _hub(fed_hub))
    assert report.passed is True
