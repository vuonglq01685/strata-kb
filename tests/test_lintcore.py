"""Tests for the shared lint primitives — specifically the notes channel,
which records checks that could not run. Ticket/mission behaviour is
covered by their own suites.
"""

from __future__ import annotations

from center_kb.doctor import Issue
from center_kb.lintcore import LintReport


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
