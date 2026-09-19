"""Tests for the DoR lint engine (`ticket.py` + `ticketlint.py`).

Hermetic: uses the `fed_hub` git fixture (from conftest.py) as the hub —
no network, no live hub, no LLM. `fed_hub` publishes two docs:
arinc-kb:arinc-424 §5.3 and icao-kb:icao-annex-2 §1.1 — the golden ticket
pins and cites both.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from strata_kb import gitio, kbcontext, ticket, ticketlint
from strata_kb.hub import HubHandle
from tests.conftest import make_stale

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
            "[arinc-kb:arinc-424 §5.3]\n"
            "- [ ] AC2: Show ICAO designation per [icao-kb:icao-annex-2 §1.1]"
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
    # No errors; the only warnings are the golden ticket's 3 unticked DoR
    # boxes (see test_unticked_definition_of_ready_boxes_are_a_warning_only
    # — the wrappers forbid the agent from ticking one itself).
    assert _errors(report) == []
    assert all(
        "Definition of Ready item is not ticked" in w
        for w in _warnings(report)
    )


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
    # Same "no errors, only the 3 unticked-DoR warnings" shape as
    # test_golden_ticket_passes above.
    assert _errors(report) == []
    assert all(
        "Definition of Ready item is not ticked" in w
        for w in _warnings(report)
    )


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


def test_leftover_comment_fence_marker_does_not_hide_an_unfilled_section(
    fed_hub: Path, golden_block: str
):
    """C1: a bare ``` a BA left in place from the template's own
    '<!-- paste an example like: ``` -->' guidance must not re-pair with
    a LATER real fence (here, '## KB context's yaml fence) and blank
    '## Use cases' out of the scan. BEFORE the `_blank_invisible` fix,
    `section_body` returned None for '## Use cases' (mistaken for
    "heading missing, already reported elsewhere"), so its literal
    'TBD' body silently passed."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "<!-- paste an example like:\n```\n-->\n"
                + _default_sections(golden_block)["## Acceptance Criteria"]
            ),
            "## Use cases": "TBD",
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any(
        "'## Use cases' is empty or only placeholder text" in m
        for m in _errors(report)
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
    make_stale(fed_hub)
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is True  # stale is a warning, not an error
    assert any(
        "stale" in msg.lower() or "changed since" in msg.lower()
        for msg in _warnings(report)
    )


def test_fail_on_stale_promotes_the_warning_to_an_error(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(golden_block)
    make_stale(fed_hub)
    report = ticketlint.lint(text, _hub(fed_hub), fail_on_stale=True)
    assert report.passed is False
    assert report.stale_errors == 1


def test_stale_errors_counts_only_stale_refs(
    fed_hub: Path, golden_block: str
):
    """Exit code 2 means 'nothing wrong but the upstream moved', so the
    count must exclude every other error."""
    text = _build_ticket(golden_block, skip="## Use cases")
    make_stale(fed_hub)
    report = ticketlint.lint(text, _hub(fed_hub), fail_on_stale=True)
    errors = len(_errors(report))
    assert report.stale_errors == 1
    assert errors > 1


# --- checks 7 & 8: citation <-> kb-context consistency ---


def test_inline_citation_not_pinned_errors(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type and level per "
                "[arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]\n"
                "- [ ] AC3: Also cross-check [crew-ops:roster-sop §3.2]"
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
                "[arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC2: Show ICAO designation using a 2-letter code "
                "(no citation needed here)"
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
                "[arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]\n"
                "- [ ] AC3: Also show altitude range between FL180 and "
                "FL220 in the tooltip"
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
    """A bracketed citation immediately followed by a sentence-ending
    period ('...[arinc-kb:arinc-424 §5.3].') must be recognized as cited
    and as resolving the pinned ref — not reported as an uncited AC, nor
    as an unresolved citation. (Historically this pinned INLINE_CITE_RE's
    trailing-period fix, commit 01e4ac2; `BRACKET_CITE_RE` sidesteps that
    whole class of bug since ']' terminates the section id, but the
    end-to-end wiring through `_check_ac_citations` and
    `check_citation_consistency` still deserves the coverage.)"""
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type per "
                "[arinc-kb:arinc-424 §5.3].\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any(
        "has no '[doc-id §section]' citation" in msg
        for msg in _warnings(report)
    )
    assert not any(
        "not in kb-context refs" in msg for msg in _errors(report)
    )
    assert report.passed is True
    # Same "no errors, only the 3 unticked-DoR warnings" shape as
    # test_golden_ticket_passes above.
    assert _errors(report) == []
    assert all(
        "Definition of Ready item is not ticked" in w
        for w in _warnings(report)
    )


def test_ac_citation_warning_counts_bracketed_citations_only():
    from strata_kb.ticketlint import _check_ac_citations

    assert _check_ac_citations(["AC1 — stored [arinc-424 §5.129]"]) == []
    assert len(_check_ac_citations(["AC1 — stored per arinc-424 §5.129"])) == 1


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
        / "strata_kb"
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


def test_golden_ticket_still_passes_with_no_new_errors(
    fed_hub: Path, golden_block: str
):
    """Regression guard: the RECOMMENDED-heading and substance checks
    (BA upgrade v2, then HIGH-1) must not introduce spurious errors on
    the golden ticket. Warnings are expected — the 3 unticked DoR boxes,
    see test_unticked_definition_of_ready_boxes_are_a_warning_only."""
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    assert report.passed is True
    assert _errors(report) == []
    assert all(
        "Definition of Ready item is not ticked" in w
        for w in _warnings(report)
    )


def test_weasel_ac_without_open_marker_warns(
    fed_hub: Path, golden_block: str
):
    doc = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Retention is configured per "
                "[arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]"
            )
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True  # warning, never an error
    assert any(
        "banned weasel phrase 'configured'" in w for w in _warnings(report)
    )


def test_weasel_ac_open_marker_suppresses_only_its_own_parentheses(
    fed_hub: Path, golden_block: str
):
    """BEFORE 0.22.0: an OPEN(...) marker anywhere on the AC line
    suppressed every weasel phrase on that line, so 'Retention is
    configured OPEN(data-team) per ...' reported nothing even though
    'configured' sat outside the marker's own parentheses. AFTER: only
    the phrase INSIDE an OPEN(...)'s own parentheses is suppressed — a
    phrase outside it still warns.
    """
    doc = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Retention is configured and the threshold "
                "is OPEN(data-team: appropriate) per "
                "[arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]"
            )
        },
    )
    report = ticketlint.lint(doc, _hub(fed_hub))
    assert report.passed is True  # warning, never an error
    # 'configured' sits outside OPEN(...)'s own parentheses — still warns.
    assert any(
        "banned weasel phrase 'configured'" in w for w in _warnings(report)
    )
    # 'appropriate' sits inside OPEN(data-team: ...)'s own parentheses —
    # suppressed, the documented owned-vagueness exception.
    assert not any(
        "banned weasel phrase 'appropriate'" in w for w in _warnings(report)
    )


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
    # RECOMMENDED_HEADINGS warnings + 1 missing-Review-record warning + 3
    # unticked-DoR-box warnings (the default '## Definition of Ready' body
    # from _default_sections ships 3 unticked rows, same as the golden
    # ticket — see test_unticked_definition_of_ready_boxes_are_a_warning_only).
    assert len(_warnings(report)) == len(ticket.RECOMMENDED_HEADINGS) + 1 + 3


def test_recommended_headings_constant_is_not_in_required():
    assert set(ticket.RECOMMENDED_HEADINGS).isdisjoint(
        set(ticket.REQUIRED_HEADINGS)
    )


def test_template_carries_every_recommended_heading():
    template_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "strata_kb"
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


def test_fabricated_kb_context_tag_errors(fed_hub: Path, golden_block: str):
    """`ticketlint` and `missionlint` share one `check_context_block`, so this
    proves the tag check reaches the ticket entry point specifically."""
    text = _build_ticket(golden_block.replace("tags: [airspace]", "tags: [ghost-tag]"))

    report = ticketlint.lint(text, _hub(fed_hub))

    assert any("ghost-tag" in e for e in _errors(report)), _errors(report)


# --- substance checks at error level (HIGH-1) ---


def test_a_ticket_of_placeholders_fails(fed_hub: Path, golden_block: str):
    """Reviewer E's T1: every required heading present, every body 'TBD'
    — DoR: PASS with warnings only, before 0.22.0."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## Summary": "TBD",
            "## Background / Business context": "",
            "## Use cases": "…",
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert report.passed is False
    assert (
        "'## Summary' is empty or only placeholder text — fill it in"
        in _errors(report)
    )
    assert (
        "'## Use cases' is empty or only placeholder text — fill it in"
        in _errors(report)
    )


def test_a_single_acceptance_criterion_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show airspace type per "
                "[arinc-kb:arinc-424 §5.3]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("at least 2 '- [ ]' items" in m for m in _errors(report))


def test_vague_acceptance_criteria_fail(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: The system shall behave correctly\n"
                "- [ ] AC2: Performance is acceptable"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert sum("no Given/When/Then" in m for m in _errors(report)) == 2


def test_duplicate_ac_ids_fail(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                "- [ ] AC1: Show type per [arinc-kb:arinc-424 §5.3]\n"
                "- [ ] AC1: Show level per [arinc-kb:arinc-424 §5.3]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any(
        "duplicate Acceptance Criterion id 'AC1'" in m for m in _errors(report)
    )


def test_a_one_letter_user_story_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={"## User Story": "As a x, I want y, so that z."},
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert sum("User Story part" in m for m in _errors(report)) == 3


def test_a_short_but_real_user_story_passes(fed_hub: Path, golden_block: str):
    """Guard against over-reach: 'BA' is a two-character role and must
    keep passing — the rule rejects a part with fewer than 2 word
    characters, not a short word."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## User Story": (
                "As a BA, I want the designator stored, so that the feed "
                "is auditable."
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("User Story part" in m for m in _errors(report))


def test_nfd_vietnamese_gwt_ac_does_not_error(fed_hub: Path, golden_block: str):
    """I1: `acquality.GWT_RE` (and the other bilingual regexes) match NFC
    text only — an NFD-encoded accented letter (macOS/IMEs; the same
    fixture shape as `test_searchdb_tokenize.py`) is base + combining
    mark, which `\\b`/literal-phrase matching does not see as the
    composed Vietnamese word. Normalizing once at the `lint()` boundary
    must make an NFD Given/When/Then AC lint clean instead of reporting
    'has no Given/When/Then'."""
    # No digit, backtick, or dotted/CamelCase identifier anywhere in this
    # line — MEASURABLE_RE must not be what accepts it; only GWT_RE can.
    ac_line = unicodedata.normalize(
        "NFD", "AC1: Giả sử có bản ghi vùng cấm, khi nhập, thì hệ thống lưu mã"
    )
    assert ac_line != unicodedata.normalize("NFC", ac_line)  # sanity: fixture is NFD

    text = _build_ticket(
        golden_block,
        overrides={
            "## Acceptance Criteria": (
                f"- [ ] {ac_line}\n"
                "- [ ] AC2: Show ICAO designation per "
                "[icao-kb:icao-annex-2 §1.1]"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert not any("has no Given/When/Then" in m for m in _errors(report))


def test_the_template_placeholder_user_story_fails(
    fed_hub: Path, golden_block: str
):
    """I3: the shipped template's own verbatim placeholder line —
    'As a <role>, I want <capability>, so that <value>.' — must not pass
    as a real story. Each bracketed part has >= 2 letters INSIDE the
    brackets ('role', 'capability', 'value'), so the length guard alone
    let it through before `is_unfilled` learned to treat a '<...>'-only
    part as unfilled."""
    text = _build_ticket(
        golden_block,
        overrides={
            "## User Story": (
                "As a <role>, I want <capability>, so that <value>."
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert sum("User Story part" in m for m in _errors(report)) == 3


def test_an_unquantified_nfr_row_fails(fed_hub: Path, golden_block: str):
    text = _build_ticket(
        golden_block,
        overrides={
            "## Non-functional requirements": (
                "| Concern | Target | How to measure | Source |\n"
                "|---|---|---|---|\n"
                "| Speed | fast | eyeball | n/a |"
            )
        },
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("no measurable Target" in m for m in _errors(report))


def test_a_definition_of_ready_with_no_rows_fails(
    fed_hub: Path, golden_block: str
):
    text = _build_ticket(
        golden_block, overrides={"## Definition of Ready": "All good."}
    )
    report = ticketlint.lint(text, _hub(fed_hub))
    assert any("no '- [ ]' checklist rows" in m for m in _errors(report))


def test_unticked_definition_of_ready_boxes_are_a_warning_only(
    fed_hub: Path, golden_block: str
):
    """The wrappers forbid the agent from ticking a box itself
    (claude-skill-ba-ticket-author.md:171-174), so an unticked checklist
    can never be an error — the golden ticket ships three unticked rows
    and still passes."""
    report = ticketlint.lint(_build_ticket(golden_block), _hub(fed_hub))
    unticked = [
        m for m in _warnings(report)
        if "Definition of Ready item is not ticked" in m
    ]
    assert len(unticked) == 3
    assert report.passed is True
