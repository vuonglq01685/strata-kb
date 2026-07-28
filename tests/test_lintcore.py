"""Tests for the shared lint primitives — specifically the notes channel,
which records checks that could not run, and `check_diagram`'s line-start
keyword anchoring. Ticket/mission behaviour is covered by their own suites.
"""

from __future__ import annotations

import pytest

from center_kb.doctor import Issue
from center_kb.lintcore import LintReport, check_diagram


def test_notes_default_to_empty():
    report = LintReport(issues=[])
    assert report.notes == []
    assert report.to_json()["notes"] == []


def test_notes_do_not_affect_pass():
    report = LintReport(issues=[], notes=["coverage check skipped"])
    assert report.passed is True
    assert report.to_json()["pass"] is True


def test_notes_render_between_issues_and_verdict():
    report = LintReport(
        issues=[Issue("warning", "a warning")],
        notes=["coverage check skipped"],
    )
    assert report.render() == (
        "[warn] a warning\n"
        "[note] coverage check skipped\n"
        "DoR: PASS"
    )


def test_notes_appear_in_json():
    report = LintReport(issues=[], notes=["n1", "n2"])
    assert report.to_json()["notes"] == ["n1", "n2"]


# --- check_diagram: line-start keyword anchoring ---


def test_diagram_passes_when_keyword_follows_an_init_directive():
    # Arrange: an init directive precedes the diagram type — the anchoring
    # exists precisely so this still matches ('flowchart' starts line 2).
    text = (
        "## Business flow\n"
        "```mermaid\n"
        "%%{init: {'theme':'neutral'}}%%\n"
        "flowchart TD\n"
        "  A --> B\n"
        "```\n"
    )

    issues = check_diagram(text, "## Business flow", ("flowchart",))

    assert issues == []


def test_diagram_fails_when_keyword_only_appears_inside_a_node_label():
    # Arrange: 'flowchart' appears only inside a node label, never at the
    # start of a line — this is the false-pass the anchoring closes.
    text = (
        "## Business flow\n"
        "```mermaid\n"
        "graph TD\n"
        "  A[flowchart of payment] --> B\n"
        "```\n"
    )

    issues = check_diagram(text, "## Business flow", ("flowchart",))

    assert len(issues) == 1
    assert issues[0].level == "error"


def test_diagram_raises_on_empty_keywords_tuple():
    # Arrange: an empty keywords tuple collapses the pattern to
    # '^[ \t]*(?:)\b', which matches almost any line — silently disabling
    # the check instead of failing loudly.
    text = "## Business flow\n```mermaid\nflowchart TD\n  A --> B\n```\n"

    with pytest.raises(ValueError):
        check_diagram(text, "## Business flow", ())
