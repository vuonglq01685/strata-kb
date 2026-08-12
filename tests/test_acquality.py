"""Tests for the banned weasel-phrase detector shared by the DoR lints."""

from __future__ import annotations

from center_kb import acquality


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


def test_open_marker_suppresses_the_line():
    line = "Retention is configured OPEN(data-team)"
    assert acquality.weasel_hits(line) == []


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
