"""Tests for the banned weasel-phrase detector shared by the DoR lints."""

from __future__ import annotations

import pytest

from strata_kb import acquality


def test_open_re_matches_owned_marker():
    assert acquality.OPEN_RE.search("Target is OPEN(design-team)")
    assert not acquality.OPEN_RE.search("no marker here")
    # An empty owner is not an owned unknown.
    assert not acquality.OPEN_RE.search("OPEN()")


def test_weasel_hits_finds_english_phrases():
    hits = acquality.weasel_hits(
        "AC1: retention is configured and response is appropriate"
    )
    assert "configured" in hits
    assert "appropriate" in hits


def test_weasel_hits_finds_vietnamese_phrases():
    assert acquality.weasel_hits("Giá trị đã cấu hình cho hệ thống") == [
        "đã cấu hình"
    ]
    assert acquality.weasel_hits("Hiển thị một tập con các trường") == [
        "một tập con"
    ]


def test_weasel_hits_is_case_insensitive():
    assert acquality.weasel_hits("Show a SUBSET of fields") == ["SUBSET"] or (
        acquality.weasel_hits("Show A Subset of fields") == ["A Subset"]
    )


def test_open_marker_mutes_only_its_own_parentheses():
    """BEFORE: an OPEN(...) anywhere on the line muted every banned
    phrase on it, so 'Values are configured OPEN(x) and appropriate and a
    subset and responsive.' reported nothing. AFTER: only the text inside
    the parentheses is muted."""
    hits = acquality.weasel_hits(
        "Values are configured OPEN(alice) and appropriate and a subset."
    )
    assert sorted(h.lower() for h in hits) == ["a subset", "appropriate", "configured"]


def test_clean_line_has_no_hits():
    assert (
        acquality.weasel_hits(
            "AC1: Show airspace type and level per arinc-424 §5.3"
        )
        == []
    )


def test_word_boundaries_avoid_substring_false_positives():
    # 'configured' must not fire inside 'preconfigured-widget-name'.
    assert acquality.weasel_hits("uses preconfigured defaults") == []


def test_distinguished_by_type_is_detected():
    assert acquality.weasel_hits(
        "Types are distinguished by type on the map"
    ) == ["distinguished by type"]


def test_distinguished_by_type_with_means_is_suppressed():
    line = (
        "Airspace areas are distinguished by type: color for restricted, "
        "shape for danger"
    )
    assert acquality.weasel_hits(line) == []


def test_phan_biet_theo_loai_with_means_is_suppressed():
    assert (
        acquality.weasel_hits("Phân biệt theo loại bằng màu và hình dạng")
        == []
    )


def test_distinguished_by_type_without_means_still_fires():
    assert acquality.weasel_hits("Areas are distinguished by type") == [
        "distinguished by type"
    ]


def test_means_word_inside_owned_marker_does_not_suppress_outside_phrase():
    """A means word (colour, label, ...) sitting INSIDE an OPEN(...)'s
    own parentheses must not suppress a CONDITIONAL_PHRASES hit that
    sits OUTSIDE it — only a means word visible outside the marker earns
    row 8's exception."""
    assert acquality.weasel_hits(
        "Areas are distinguished by type OPEN(alice: by colour)"
    ) == ["distinguished by type"]


@pytest.mark.parametrize(
    "body",
    ["", "TBD", "  tbd  ", "TODO", "N/A", "...", "…", "<...>", "-", "xxx",
     "chưa rõ", "đang cập nhật",
     # I3: the shipped templates' own angle-bracket placeholders — a body
     # that reduces to nothing but '<...>' spans (plus punctuation) once
     # they are removed is unfilled, whatever prose sits inside the
     # brackets.
     "<role>",
     "<context; every industry-standard claim cites `[doc-id §section]`>"],
)
def test_is_unfilled_true_for_placeholders(body):
    assert acquality.is_unfilled(body) is True


@pytest.mark.parametrize(
    "body",
    ["The importer stores the designator.", "Bộ nhập lưu mã định danh.",
     "5 seconds", "None", "N/A - no retention policy applies",
     # I3: a real '<' with no closing '>' anywhere (a comparison, not a
     # placeholder) must not be mistaken for one.
     "latency < 200 ms p95"],
)
def test_is_unfilled_false_for_real_content(body):
    assert acquality.is_unfilled(body) is False


def test_gwt_detects_both_languages():
    assert acquality.GWT_RE.search(
        "Given a Restrictive Airspace record, when it is imported, then …"
    )
    assert acquality.GWT_RE.search(
        "Giả sử có bản ghi vùng cấm, khi nhập, thì hệ thống lưu mã"
    )
    assert not acquality.GWT_RE.search("The system stores the designator")


@pytest.mark.parametrize(
    "item",
    [
        "AC1 — Given a record, when imported, then it is stored",
        "AC2 — the importer stores at most 200 records per batch",
        "AC3 — response time <= 2s",
        "AC4 — writes `runway_designator` to the feed table",
        "AC5 — the threshold is OPEN(alice)",
    ],
)
def test_ac_substance_accepts(item):
    assert acquality.ac_substance(item) is None


@pytest.mark.parametrize(
    "item",
    [
        "AC1 — The system shall behave correctly and handle all edge cases",
        "AC2 — Performance is acceptable and the data is validated properly",
        "AC3 — the threshold is OPEN(TBD)",
        "AC4 — the threshold is OPEN(?)",
    ],
)
def test_ac_substance_rejects(item):
    assert acquality.ac_substance(item) is not None


def test_ac_substance_reason_text():
    """Pins the exact reason string ticketlint/missionlint (Tasks 6/8)
    embed verbatim into their own error/warning message."""
    assert acquality.ac_substance(
        "AC1 — The system shall behave correctly and handle all edge cases"
    ) == (
        "has no Given/When/Then, no measurable value (a number, a "
        "comparison, or a named identifier) and no owned OPEN(<owner>)"
    )


def test_measurable_re_does_not_mistake_e_g_for_a_dotted_identifier():
    # 'e.g.' is one letter, a dot, one letter — not a dotted identifier
    # like 'user.email' (2+ characters per segment).
    assert not acquality.MEASURABLE_RE.search("e.g. responsive")
    assert acquality.MEASURABLE_RE.search("writes to user.email")


def test_ac_substance_rejects_despite_e_g_dotted_look_alike():
    assert (
        acquality.ac_substance("AC1 — The system is fast, e.g. responsive")
        is not None
    )


@pytest.mark.parametrize(
    "item",
    [
        # The real caller's form: tests/test_ticketlint.py:800 hands
        # ac_substance exactly '- [ ] AC1: <text>' with the checkbox
        # stripped, i.e. 'AC1: <text>'.
        "AC1: The system shall behave correctly and handle all edge cases",
        # Case-insensitive, with or without a space before the digit.
        "Ac1: The system shall behave correctly and handle all edge cases",
        "ac1: The system shall behave correctly and handle all edge cases",
        "AC 1: The system shall behave correctly and handle all edge cases",
        # Markdown emphasis and brackets around the id.
        "**AC1**: The system shall behave correctly and handle all edge cases",
        "[AC1] The system shall behave correctly and handle all edge cases",
        # A dotted sub-id.
        "AC1.1: The system shall behave correctly and handle all edge cases",
    ],
)
def test_ac_substance_rejects_across_real_world_id_forms(item):
    """A digit inside the AC id — in whatever spelling the BA actually
    typed — must never itself satisfy MEASURABLE_RE; only the body after
    the id counts. Every one of these carries a vague body with no
    Given/When/Then, no owned unknown, and no measurable value, so every
    form must still be rejected."""
    assert acquality.ac_substance(item) is not None


def test_owned_open_markers_ignores_placeholder_owners():
    assert acquality.owned_open_markers("value OPEN(alice)") == ["OPEN(alice)"]
    assert acquality.owned_open_markers("value OPEN(TBD)") == []
    assert acquality.owned_open_markers("value OPEN(?)") == []


def test_nfr_target_ok():
    assert acquality.nfr_target_ok("p95 < 200 ms") is True
    assert acquality.nfr_target_ok("OPEN(alice)") is True
    assert acquality.nfr_target_ok("fast") is False
    assert acquality.nfr_target_ok("") is False
    # An unowned marker is the same placeholder-in-owner's-clothing as
    # everywhere else in this module — not a target.
    assert acquality.nfr_target_ok("OPEN(TBD)") is False


def test_open_marker_still_mutes_a_phrase_inside_it():
    assert acquality.weasel_hits("threshold OPEN(alice: appropriate?)") == []


def test_open_marker_with_unowned_owner_does_not_mute():
    """An unowned OPEN(...) (TBD, ?, ...) is a placeholder wearing the
    costume of an owner: it must not license anything inside its own
    parentheses either, so a weasel phrase there still reports."""
    assert acquality.weasel_hits(
        "threshold OPEN(TBD: appropriate)"
    ) == ["appropriate"]
    assert acquality.weasel_hits(
        "threshold OPEN(?: appropriate)"
    ) == ["appropriate"]


def test_parse_review_row_accepts_a_well_formed_row():
    row = acquality.parse_review_row(
        ["2026-09-08", "1", "4", "5", "business-reviewer"]
    )
    assert isinstance(row, acquality.ReviewRow)
    assert (row.round, row.business, row.dev) == (1, 4, 5)


@pytest.mark.parametrize(
    "cells",
    [
        ["2026-09-08", "1", "5", "5", ""],          # empty reviewer
        ["2026-09-08", "one", "5", "5", "me"],      # round not an int
        ["2026-09-08", "0", "5", "5", "me"],        # round < 1
        ["2026-09-08", "1", "nine", "5", "me"],     # score not an int
        ["2026-09-08", "1", "9", "5", "me"],        # score out of range
        ["2026-09-08", "1", "5", "5"],              # four cells
    ],
)
def test_parse_review_row_rejects(cells):
    assert isinstance(acquality.parse_review_row(cells), str)


@pytest.mark.parametrize(
    ("cells", "reason"),
    [
        (
            ["2026-09-08", "1", "5", "5"],
            "has 4 cells; the table has 5 columns",
        ),
        (
            ["2026-09-08", "1", "5", "5", ""],
            "has an empty cell; every column must be filled",
        ),
        (
            ["2026-09-08", "one", "5", "5", "me"],
            "Round 'one' is not a whole number",
        ),
        (
            ["2026-09-08", "0", "5", "5", "me"],
            "Round '0' must be 1 or more",
        ),
        (
            ["2026-09-08", "1", "nine", "5", "me"],
            "Business score 'nine' is not a whole number",
        ),
        (
            ["2026-09-08", "1", "9", "5", "me"],
            "Business score '9' is outside the 1–5 maturity scale",
        ),
    ],
)
def test_parse_review_row_reason_text(cells, reason):
    """Pins the exact reason string ticketlint/missionlint (Tasks 6/8)
    embed verbatim into their own error/warning message, one case per
    malformed-row branch (cell count, empty cell, round not an int,
    round < 1, score not an int, score out of range)."""
    assert acquality.parse_review_row(cells) == reason
