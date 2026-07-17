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
        "## KB context": f"```yaml\n{block}\n```",
        "## Definition of Ready": (
            "- [ ] Story, ACs, use cases, both diagrams present\n"
            "- [ ] Every citation resolves at the pinned version "
            "(kb ticket lint PASS)\n"
            "- [ ] No stale refs"
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
    for heading in ticket.REQUIRED_HEADINGS:
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
    assert set(data.keys()) == {"pass", "errors", "warnings"}
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
