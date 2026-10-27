from strata_kb.l3check.detect import (
    MIN_RUN,
    SectionInput,
    content_findings,
    normalize_words,
    strip_markdown,
    unverifiable,
)

PAGE = (
    "The quick brown fox jumps over the lazy dog while the "
    "river runs quietly past the old stone mill"
)


def _sec(l3: str, page: int | None = 1, end_page: int | None = 1) -> SectionInput:
    return SectionInput(id="1", chapter="A", page=page, end_page=end_page, l3=l3)


def test_normalize_rejoins_hyphenation_and_keeps_vietnamese():
    assert normalize_words("exam-\nple Gốc") == ["example", "gốc"]


def test_strip_markdown_table_and_image():
    md = (
        "## Heading\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "![alt text](img/x.png)\n\n```py\ncode\n```\n\n*em* and __strong__\n"
    )
    assert normalize_words(strip_markdown(md)) == [
        "heading", "a", "b", "1", "2", "alt", "text", "code", "em", "and", "strong",
    ]  # fmt: skip


def test_identical_text_gives_no_findings():
    pdf = {1: "Running header\n" + PAGE}
    sec = _sec(PAGE)
    assert content_findings(sec, "", pdf, {1: ["Running header "]}) == []


def test_missing_run_reported_with_page():
    extra = "alpha bravo charlie delta echo foxtrot golf hotel"
    pdf = {1: PAGE + "\n" + extra}
    findings = content_findings(_sec(PAGE), "", pdf, {})
    assert len(findings) == 1
    assert findings[0].kind == "content"
    assert findings[0].page == 1
    assert findings[0].evidence == {"pdf": extra}


def test_neighbour_text_counts_as_present():
    extra = "alpha bravo charlie delta echo foxtrot golf hotel"
    pdf = {1: PAGE + "\n" + extra}
    assert content_findings(_sec(PAGE), extra, pdf, {}) == []


def test_garbled_l3_reported():
    garbled = "g ố c r ễ"
    l3 = PAGE + " " + garbled + " " + PAGE
    pdf = {1: PAGE + " " + PAGE}
    findings = content_findings(_sec(l3), "", pdf, {})
    assert len(findings) == 1
    assert findings[0].kind == "content"
    assert findings[0].page == 1
    assert findings[0].evidence == {"l3": "g ố c r ễ"}


def test_short_diff_below_min_run_ignored():
    pdf = {1: PAGE + " one two three"}
    assert MIN_RUN > 3
    assert content_findings(_sec(PAGE), "", pdf, {}) == []


def test_scanned_pages_unverifiable():
    sec = _sec("text", page=2, end_page=3)
    finding = unverifiable(sec, {2: "", 3: "  \n"})
    assert finding is not None
    assert (finding.kind, finding.page) == ("unverifiable", 2)
    assert unverifiable(sec, {2: "", 3: PAGE}) is None
    assert unverifiable(_sec("x", page=None, end_page=None), {}) is None
    assert content_findings(_sec("x", page=None, end_page=None), "", {}, {}) == []


def test_run_spanning_page_break_is_one_finding():
    a, b = "alpha bravo charlie delta", "echo foxtrot golf hotel"
    pdf = {1: PAGE + " " + a, 2: b + " " + PAGE}
    findings = content_findings(_sec(PAGE + " " + PAGE, end_page=2), "", pdf, {})
    assert [(f.page, f.evidence) for f in findings] == [(1, {"pdf": f"{a} {b}"})]


def test_run_starting_on_second_page_reports_that_page():
    extra = "alpha bravo charlie delta echo foxtrot"
    pdf = {1: PAGE, 2: extra + " " + PAGE}
    findings = content_findings(_sec(PAGE + " " + PAGE, end_page=2), "", pdf, {})
    assert [(f.page, f.evidence) for f in findings] == [(2, {"pdf": extra})]


def test_markdown_link_keeps_text_not_url():
    assert normalize_words(strip_markdown("see [the doc](https://x.com/a.pdf) now")) == [
        "see", "the", "doc", "now",
    ]  # fmt: skip
    l3 = PAGE + " [guide](https://www.example.com/path/to/doc.pdf)"
    assert content_findings(_sec(l3), "", {1: PAGE + " guide"}, {}) == []


def test_short_side_falls_back_to_word_presence():
    findings = content_findings(_sec("hi"), "", {1: "one two three four five"}, {})
    assert [(f.page, f.evidence) for f in findings] == [
        (1, {"pdf": "one two three four five"})
    ]
