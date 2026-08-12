"""Tests for the DoR lint engine (`ticket.py` + `ticketlint.py`).

Hermetic: uses the `fed_hub` git fixture (from conftest.py) as the hub —
no network, no live hub, no LLM. `fed_hub` publishes two docs:
arinc-kb:arinc-424 §5.3 and icao-kb:icao-annex-2 §1.1 — the golden ticket
pins and cites both.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from center_kb import gitio, kbcontext, ticket, ticketlint
from center_kb.hub import HubHandle

DEFAULT_TITLE = "# TAL-1580 — Show restrictive airspace details"

REFS = ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"]

# Template order: required + recommended sections, recommended ones
# inserted before '## KB context' exactly as in ticket-template.md.
ALL_HEADINGS = (
    "## Summary",
    "## User Story",
    "## Background / Business context",
    "## Acceptance Criteria",
    "## Use cases",
    "## Sequence diagram",
    "## Business flow",
    "## Dependencies",
    "## Non-functional requirements",
    "## UI / presentation spec",
    "## Out of scope",
    "## Test data & verification",
    "## Open questions",
    "## KB context",
    "## Definition of Ready",
    "## Review record",
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
            "Dispatchers need restrictive airspace details while planning "
            "a route."
        ),
        "## User Story": (
            "As a dispatcher, I want to see restrictive airspace details, "
            "so that I can brief the flight crew accurately."
        ),
        "## Background / Business context": (
            "Restrictive airspace records define designation, type, and "
            "level."
        ),
        "## Acceptance Criteria": (
            "- [ ] AC1: Show airspace type and level per "
            "arinc-kb:arinc-424 §5.3\n"
            "- [ ] AC2: Show ICAO designation per icao-kb:icao-annex-2 §1.1"
        ),
        "## Use cases": (
            "### Main flow\n"
            "Dispatcher opens the map and clicks the airspace polygon.\n\n"
            "### Alternate / exception flows\n"
            "No restrictive airspace nearby: show nothing."
        ),
        "## Sequence diagram": (
            "```mermaid\n"
            "sequenceDiagram\n"
            "  Dispatcher->>System: Request airspace info\n"
            "  System-->>Dispatcher: Airspace details\n"
            "```"
        ),
        "## Business flow": (
            "```mermaid\n"
            "flowchart TD\n"
            "  A[Start] --> B[Fetch airspace data]\n"
            "  B --> C[Display to dispatcher]\n"
            "```"
        ),
        "## Dependencies": "- Blocked by: None\n- Blocks: None",
        "## Non-functional requirements": (
            "| Concern | Target | How to measure | Source |\n"
            "|---|---|---|---|\n"
            "| Detail render | Details visible within 2 s of polygon "
            "click | Stopwatch check on staging | team SLA |"
        ),
        "## UI / presentation spec": (
            "Side panel lists designation, type, and level as labeled "
            "rows; empty state shows 'No restrictive airspace nearby'."
        ),
        "## Out of scope": "Editing airspace records.",
        "## Test data & verification": (
            "Sample record with designation R-2905A: expect type 'R' and "
            "level 'L1' shown in the panel."
        ),
        "## Open questions": (
            "- [ ] Q1 — Confirm the polygon fill color token — "
            "owner: design-team — blocks: UI spec"
        ),
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": (
            "- [ ] Story, ACs, use cases, both diagrams present\n"
            "- [ ] Every citation resolves at the pinned version "
            "(kb ticket lint PASS)\n"
            "- [ ] No stale refs"
        ),
        "## Review record": (
            "| Date | Round | Business | Dev | Reviewer |\n"
            "|---|---|---|---|---|\n"
            "| 2026-08-12 | 1 | 4 | 4 | agent |\n\n"
            "Open gaps: none"
        ),
    }


def _build_ticket(
    block: str,
    *,
    skip: str | None = None,
    title: str = DEFAULT_TITLE,
    overrides: dict[str, str] | None = None,
) -> str:
    sections = _default_sections(block)
    if overrides:
        sections.update(overrides)
    parts = [title, ""]
    for heading in ALL_HEADINGS:
        if heading == skip:
            continue
        parts.append(heading)
        parts.append(sections[heading])
        parts.append("")
    return "\n".join(parts)


def _errors(report: ticketlint.LintReport) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report: ticketlint.LintReport) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


# --- golden tickets ---


def test_golden_ticket_passes(fed_hub: Path, golden_block: str):
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert report.passed is True
    assert report.issues == []


def test_vietnamese_golden_ticket_passes(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        title="# TAL-1580 — Hiển thị vùng cấm bay",
        overrides={
            "## Summary": (
                "Điều phối viên cần xem chi tiết vùng cấm bay khi lập kế "
                "hoạch bay."
            ),
            "## Background / Business context": (
                "Bản ghi vùng cấm bay xác định loại, mức và giới hạn độ cao."
            ),
            "## User Story": (
                "As a dispatcher (điều phối viên), I want to xem "
                "restrictive airspace, so that tôi có thể đảm bảo an toàn "
                "chuyến bay."
            ),
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is True
    assert report.issues == []


# --- check 1: required headings + title ---


@pytest.mark.parametrize("heading", ticket.REQUIRED_HEADINGS)
def test_missing_heading_errors(fed_hub: Path, golden_block: str, heading: str):
    text = _build_ticket(golden_block, skip=heading)
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any(heading in msg for msg in _errors(report))


def test_heading_inside_a_fence_is_reported_missing(
    fed_hub: Path, golden_block: str
):
    """A required heading quoted inside a fenced code block — e.g. a BA
    pasting a reference ticket into their own document as a worked example
    — must not satisfy the presence check. Regression test for the
    fence-aware `lintcore.check_headings` fix (shared with `kb mission
    lint`)."""
    text = _build_ticket(golden_block)
    fenced = text.replace(
        "## Summary\n", "```markdown\n## Summary\n```\n", 1
    )
    assert fenced != text  # sanity: the replace actually matched

    report = ticketlint.lint(fenced, _hub(fed_hub))

    assert report.passed is False
    assert any(
        "missing required heading: '## Summary'" in m for m in _errors(report)
    )


def test_missing_title_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(golden_block, title="Not a title line")
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("title" in msg.lower() for msg in _errors(report))


# --- check 2: user story format ---


def test_bad_story_line_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={"## User Story": "The dispatcher wants better tooling."},
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("User Story" in msg for msg in _errors(report))


# --- check 3: acceptance criteria checkboxes ---


def test_zero_ac_items_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={"## Acceptance Criteria": "No checkboxes here, just prose."},
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("Acceptance Criteria" in msg for msg in _errors(report))


# --- check 4: mermaid diagrams ---


def test_sequence_diagram_missing_fence_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(golden_block, overrides={"## Sequence diagram": "TBD."})
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("Sequence diagram" in msg for msg in _errors(report))


def test_sequence_diagram_wrong_keyword_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Sequence diagram": "```mermaid\nflowchart TD\n  A --> B\n```"
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("Sequence diagram" in msg for msg in _errors(report))


def test_business_flow_missing_fence_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(golden_block, overrides={"## Business flow": "TBD."})
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("Business flow" in msg for msg in _errors(report))


def test_business_flow_wrong_keyword_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Business flow": "```mermaid\nsequenceDiagram\n  A->>B: hi\n```"
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("Business flow" in msg for msg in _errors(report))


# --- check 5: kb-context parses ---


def test_malformed_kb_context_yaml_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={"## KB context": "```yaml\nkb-context:\n  version: [1, 2\n```"},
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any(
        "valid YAML" in msg or "kb-context" in msg for msg in _errors(report)
    )


# --- check 6: ref resolution (broken / stale) ---


def test_broken_ref_errors(fed_hub: Path, golden_block: str):
    rev = gitio.head_commit(gitio.git_root(fed_hub))
    bad_block = (
        f"kb-context:\n  version: {rev}\n  refs:\n    - arinc-kb:arinc-424 §9.9\n"
    )
    text = _build_ticket(
        golden_block,
        overrides={
            "## KB context": f"```yaml\n{bad_block}```",
            "## Acceptance Criteria": (
                "- [ ] AC1: Show something per arinc-kb:arinc-424 §9.9"
            ),
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("9.9" in msg for msg in _errors(report))


def test_stale_ref_warns(fed_hub: Path, golden_block: str):
    text = _build_ticket(golden_block)
    l2 = fed_hub / "federation" / "icao-kb" / "icao-annex-2" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8") + "\nEdited after publish.\n",
        encoding="utf-8",
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is True  # stale is a warning, not an error
    assert any(
        "stale" in msg.lower() or "changed since" in msg.lower()
        for msg in _warnings(report)
    )


# --- checks 7 & 8: citation <-> kb-context consistency ---


def test_inline_citation_not_pinned_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type and level per "
                "arinc-kb:arinc-424 §5.3\n"
                "- [ ] AC2: Show ICAO designation per icao-kb:icao-annex-2 "
                "§1.1\n"
                "- [ ] AC3: Also cross-check crew-ops:roster-sop §3.2"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("roster-sop" in msg for msg in _errors(report))


def test_pinned_ref_never_cited_warns(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type and level per "
                "arinc-kb:arinc-424 §5.3\n"
                "- [ ] AC2: Show ICAO designation (no citation needed here)"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("icao-annex-2" in msg for msg in _warnings(report))


# --- check 9: AC without any citation ---


def test_ac_without_citation_warns(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type and level per "
                "arinc-kb:arinc-424 §5.3\n"
                "- [ ] AC2: Show ICAO designation per icao-kb:icao-annex-2 "
                "§1.1\n"
                "- [ ] AC3: Also show altitude range in the tooltip"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "altitude range" in msg or "AC3" in msg for msg in _warnings(report)
    )


def test_ac_citation_ending_a_sentence_produces_no_false_warnings(
    fed_hub: Path, golden_block: str
):
    """Ties the INLINE_CITE_RE trailing-period fix (lintcore.py, commit
    01e4ac2) to the actual gates it feeds: `_check_ac_citations` and
    `check_citation_consistency`. An AC whose citation ends the sentence
    ('... arinc-kb:arinc-424 §5.3.') must be recognized as cited and as
    resolving the pinned ref — not reported as an uncited AC, nor as an
    unresolved citation."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type per arinc-kb:arinc-424 §5.3.\n"
                "- [ ] AC2: Show ICAO designation per icao-kb:icao-annex-2 "
                "§1.1"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("has no citation" in msg for msg in _warnings(report))
    assert not any(
        "not in kb-context refs" in msg for msg in _errors(report)
    )
    assert report.passed is True
    assert report.issues == []


# --- passed / to_json ---


def test_passed_false_iff_error_present(fed_hub: Path, golden_block: str):
    good = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert good.passed is True

    bad = ticketlint.lint(
        _build_ticket(golden_block, skip="## Summary"), _hub(fed_hub)
    )
    assert bad.passed is False
    assert any(i.level == "error" for i in bad.issues)


def test_to_json_shape(fed_hub: Path, golden_block: str):
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    data = report.to_json()
    assert set(data.keys()) == {"pass", "errors", "warnings", "notes"}
    assert data["pass"] is True
    assert data["errors"] == []
    assert isinstance(data["warnings"], list)


# --- hub unreachable ---


def test_hub_none_single_error_no_crash(fed_hub: Path, golden_block: str):
    text = _build_ticket(golden_block)
    report = ticketlint.lint(text, None)
    assert report.passed is False
    errors = _errors(report)
    assert len(errors) == 1
    assert "hub unreachable" in errors[0]


# --- render() ---


def test_render_ends_with_dor_line(fed_hub: Path, golden_block: str):
    passing = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert passing.render().splitlines()[-1] == "DoR: PASS"

    failing = ticketlint.lint(
        _build_ticket(golden_block, skip="## Summary"), _hub(fed_hub)
    )
    assert failing.render().splitlines()[-1] == "DoR: FAIL"


# --- template sync ---


def test_template_headings_match_contract():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "center_kb"
        / "templates"
        / "init"
        / "ticket-template.md"
    )
    content = template_path.read_text(encoding="utf-8")
    for heading in ticket.REQUIRED_HEADINGS:
        assert content.count(heading) == 1, heading


# --- check 10: parent mission back-link ---


def _mission_doc(mission_id: str, us_ids: list[str]) -> str:
    rows = "\n".join(f"| {u} | Story {u} |" for u in us_ids)
    return (
        f"# Mission {mission_id}\n\n"
        f"> Mission: {mission_id}\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        f"{rows}\n"
    )


def test_ticket_without_parent_mission_line_is_unaffected(
    fed_hub: Path, golden_block: str
):
    """REQUIRED_HEADINGS is untouched and the back-link is optional, so
    every pre-existing ticket keeps passing with no edit."""
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert report.passed is True
    assert report.notes == []


def test_valid_parent_mission_passes(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    missions = tmp_path / "missions"
    missions.mkdir()
    (missions / "M-airspace-filter.md").write_text(
        _mission_doc("M-airspace-filter", ["M-airspace-filter-US1"]),
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is True, _errors(report)
    assert report.notes == []


def test_missing_mission_file_errors(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    missions = tmp_path / "missions"
    missions.mkdir()
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is False
    assert any("mission file not found" in m for m in _errors(report))


def test_unreadable_mission_file_errors_instead_of_crashing(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """A mission .md saved as non-UTF-8 (e.g. cp1252, plausible when a BA
    pastes a smart quote) must produce an [error] line, not a raw
    UnicodeDecodeError escaping out of lint()."""
    missions = tmp_path / "missions"
    missions.mkdir()
    (missions / "M-airspace-filter.md").write_bytes(
        b"caf\xe9 - not valid utf-8"
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is False
    assert any("could not read mission file" in m for m in _errors(report))


def test_us_id_absent_from_backlog_errors(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    missions = tmp_path / "missions"
    missions.mkdir()
    (missions / "M-airspace-filter.md").write_text(
        _mission_doc("M-airspace-filter", ["M-airspace-filter-US9"]),
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is False
    assert any("not in the backlog" in m for m in _errors(report))


def test_malformed_parent_mission_id_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: airspace-filter",
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("M-<slug>" in m for m in _errors(report))


def test_empty_parent_mission_value_errors(fed_hub: Path, golden_block: str):
    """'> Parent mission:' with nothing after the colon does not match
    PARENT_MISSION_RE at all (it requires >= 1 non-space char), so without
    the line-presence check this reads as "no parent mission" and passes
    clean — exactly the half-written back-link a BA must be warned about."""
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission:",
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("has no mission id" in m for m in _errors(report))


def test_whitespace_only_parent_mission_value_errors(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission:    ",
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert any("has no mission id" in m for m in _errors(report))


def test_not_in_backlog_message_names_the_mission_lint_escape_hatch(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """`check_backlog` returns an EMPTY id list (with its own error) when
    the mission's backlog table lost its header row — so a ticket that
    really is in the mission's backlog can still get "not in the backlog"
    here, fail-closed but dead-ending the BA. The message must point at
    `kb mission lint` as the other possible cause, without ticketlint
    surfacing the mission's own issues directly."""
    missions = tmp_path / "missions"
    missions.mkdir()
    mission_path = missions / "M-airspace-filter.md"
    mission_path.write_text(
        "# Mission M-airspace-filter\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        # header row missing — check_backlog errors and returns [] ids.
        "| M-airspace-filter-US1 | Render polygons |\n",
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is False
    assert any(
        "kb mission lint" in m and str(mission_path) in m
        for m in _errors(report)
    )


def test_backlog_errors_elsewhere_warn_instead_of_silently_passing(
    fed_hub: Path, golden_block: str, tmp_path: Path
):
    """The two DoR gates must not silently disagree about what counts as a
    valid US id. `check_backlog` still finds a zero-padded id like
    'M-airspace-filter-US01' verbatim in `backlog_ids` (membership only
    checks the string is in the table), even though it also raises its own
    error for that row failing `mission.us_id_re`'s pattern (mission lint
    rejects it as malformed). Without this warning, a ticket named
    'M-airspace-filter-US01.md' would pass check 10 clean while `kb mission
    lint` fails the very row it points at — this pins that the ticket
    report at least WARNS, and that it never leaks the mission's own error
    text (that belongs to the mission's own PR, per
    test_not_in_backlog_message_names_the_mission_lint_escape_hatch
    above)."""
    missions = tmp_path / "missions"
    missions.mkdir()
    mission_path = missions / "M-airspace-filter.md"
    mission_path.write_text(
        _mission_doc("M-airspace-filter", ["M-airspace-filter-US01"]),
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US01.md"
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )

    report = ticketlint.lint(
        text, _hub(fed_hub), path=ticket_path, missions_dir=missions
    )

    assert report.passed is True  # membership was found; this is a warning
    assert any(
        "backlog has errors" in w and "kb mission lint" in w
        for w in _warnings(report)
    )
    # The mission's own issue text ("does not match") must not leak through.
    assert not any("does not match" in w for w in _warnings(report))
    assert not any("does not match" in e for e in _errors(report))


def test_parent_mission_without_paths_degrades_to_a_note(
    fed_hub: Path, golden_block: str
):
    """This is the MCP path: no repo on disk, so existence and backlog
    membership cannot be checked. It must say so, not imply a full PASS."""
    text = _build_ticket(
        golden_block,
        title=f"{DEFAULT_TITLE}\n\n> Parent mission: M-airspace-filter",
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is True
    assert any("parent-mission" in n for n in report.notes)


# --- new-template warnings (BA upgrade v2) ---


def test_golden_ticket_still_passes_with_no_issues(
    fed_hub: Path, golden_block: str
):
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert report.passed is True
    assert report.issues == []


def test_weasel_ac_without_open_marker_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Retention is configured per "
                "arinc-kb:arinc-424 §5.3\n"
                "- [ ] AC2: Show ICAO designation per "
                "icao-kb:icao-annex-2 §1.1"
            )
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True  # warning, never an error
    assert any(
        "banned weasel phrase 'configured'" in w for w in _warnings(report)
    )


def test_weasel_ac_with_open_marker_is_suppressed(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Retention is configured OPEN(data-team) per "
                "arinc-kb:arinc-424 §5.3\n"
                "- [ ] AC2: Show ICAO designation per "
                "icao-kb:icao-annex-2 §1.1"
            )
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert not any("weasel" in w for w in _warnings(report))


def test_orphan_open_marker_warns_when_open_questions_has_no_rows(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## UI / presentation spec": "OPEN(design-team)",
            "## Open questions": "None yet.",
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "every unknown needs an owned row" in w for w in _warnings(report)
    )


def test_open_marker_with_matching_row_is_clean(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## UI / presentation spec": "OPEN(design-team)",
            "## Open questions": (
                "- [ ] Q1 — UI spec needs design input — "
                "owner: design-team — blocks: UI / presentation spec"
            ),
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert not any("owned row" in w for w in _warnings(report))


def test_ownerless_open_question_row_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## Open questions": "- [ ] Q1 — nobody owns this question"
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert any("no 'owner:'" in w for w in _warnings(report))


def test_missing_recommended_section_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(golden_block, skip="## Dependencies")
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "recommended section missing: '## Dependencies'" in w
        for w in _warnings(report)
    )


def test_legacy_nine_section_ticket_still_passes(
    fed_hub: Path, golden_block: str
):
    """A pre-upgrade ticket (only the 9 required sections) keeps DoR: PASS
    — the new checks are warnings, REQUIRED_HEADINGS is untouched."""
    sections = _default_sections(golden_block)
    parts = [DEFAULT_TITLE, ""]
    for heading in ticket.REQUIRED_HEADINGS:
        parts.append(heading)
        parts.append(sections[heading])
        parts.append("")
    report = ticketlint.lint("\n".join(parts), _hub(fed_hub))
    assert report.passed is True
    # RECOMMENDED_HEADINGS warnings + 1 missing-Review-record warning.
    assert len(_warnings(report)) == len(ticket.RECOMMENDED_HEADINGS) + 1


def test_recommended_headings_constant_is_not_in_required():
    assert set(ticket.RECOMMENDED_HEADINGS).isdisjoint(
        set(ticket.REQUIRED_HEADINGS)
    )


def test_template_carries_every_recommended_heading():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "center_kb"
        / "templates"
        / "init"
        / "ticket-template.md"
    )
    content = template_path.read_text(encoding="utf-8")
    for heading in ticket.RECOMMENDED_HEADINGS:
        assert content.count(heading) == 1, heading
    assert "docs/ac-quality.md" in content


def test_missing_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(golden_block, skip="## Review record")
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any(
        "'## Review record' missing" in w for w in _warnings(report)
    )


def test_placeholder_review_record_warns_but_passes(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={"## Review record": "Not yet reviewed."},
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True
    assert any("placeholder" in w for w in _warnings(report))


def test_filled_review_record_emits_no_review_warning(
    fed_hub: Path, golden_block: str
):
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert not any("Review record" in w for w in _warnings(report))
