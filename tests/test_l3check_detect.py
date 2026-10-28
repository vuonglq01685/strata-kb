from strata_kb import quality
from strata_kb.ingest.sectioner import Fallback, Inversion, SectioningNotes
from strata_kb.l3check.detect import (
    EVIDENCE_CHARS,
    MIN_RUN,
    SectionInput,
    break_findings,
    check_document,
    content_findings,
    enclosing_unit,
    fallback_findings,
    normalize_words,
    order_findings,
    strip_markdown,
    unverifiable,
)
from strata_kb.l3check.report import Finding

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


# --- break / order / fallback / whole document ---

_BREAK_PDF = (
    "The committee reviewed the annual budget and agreed that the new "
    "policy should apply to every department across the whole organisation."
)


def test_break_detected_when_pdf_is_contiguous():
    l3 = (
        "The committee reviewed the annual budget and agreed that the new\n\n"
        "policy should apply to every department across the whole organisation."
    )
    findings = break_findings(_sec(l3), {1: _BREAK_PDF})
    assert len(findings) == 1
    assert findings[0].kind == "break"
    assert findings[0].page == 1
    assert findings[0].evidence == {
        "l3": "The committee reviewed the annual budget and agreed that the new",
        "next": "policy should apply to every department across the whole organisation.",
        "pdf": _BREAK_PDF.rstrip("."),
    }


def _long_break(n: int = 80) -> tuple[str, list[str], list[str], str]:
    a = [f"aa{i}x" for i in range(n)]
    b = [f"bb{i}x" for i in range(n)]
    l3 = " ".join(a) + "\n\n" + " ".join(b) + "."
    words = a + b
    pdf = "\n".join(" ".join(words[i : i + 10]) for i in range(0, len(words), 10))
    return l3, a, b, pdf


def test_break_evidence_is_raw_paragraph_ends_and_pdf_window_around_the_join():
    l3, a, b, pdf = _long_break()
    (finding,) = break_findings(_sec(l3), {1: pdf})
    assert finding.evidence["l3"].split() == a[-40:]
    assert finding.evidence["next"].split() == b[:40]
    assert finding.evidence["pdf"].split() == a[-60:] + b[:60]
    assert "\n" in finding.evidence["pdf"]  # line structure kept for the judge


def test_break_evidence_is_size_capped():
    l3, a, b, _ = _long_break(8)
    pdf = (" " * 3000).join(a + b)
    (finding,) = break_findings(_sec(l3), {1: pdf})
    assert len(finding.evidence["pdf"]) <= 2 * EVIDENCE_CHARS


def test_break_page_is_the_page_of_the_join():
    l3, a, b, _ = _long_break(8)
    pdf = {1: "filler words that fill the first page", 2: " ".join(a + b)}
    (finding,) = break_findings(_sec(l3, page=1, end_page=2), pdf)
    assert finding.page == 2


def test_break_not_flagged_after_full_stop():
    l3 = "The committee reviewed the annual budget.\n\nPolicy should apply to every department."
    pdf = {
        1: "The committee reviewed the annual budget. Policy should apply to every department."
    }
    assert break_findings(_sec(l3), pdf) == []


def test_break_not_flagged_when_pdf_has_a_real_gap():
    l3 = (
        "The committee reviewed the annual budget and agreed that the new\n\n"
        "policy should apply to every department across the whole organisation."
    )
    pdf = {
        1: "agreed that the new\nUnrelated footer text\npolicy should apply to every"
    }
    assert break_findings(_sec(l3), pdf) == []


def test_list_items_not_flagged_as_break():
    l3 = "Steps follow and then\n\n- policy should apply to every department\n\n1. more words here today"
    pdf = {
        1: "Steps follow and then policy should apply to every department more words here today"
    }
    assert break_findings(_sec(l3), pdf) == []


def test_break_not_flagged_across_tight_list():
    l3 = "Steps are:\n- open the valve\n- close the door\n\nAfter that the system restarts."
    pdf = {1: "open the valve close the door After that the system restarts"}
    assert break_findings(_sec(l3), pdf) == []


def test_break_not_flagged_across_tight_heading():
    l3 = "Body ends here\n## 2 Scope\n\nThis section covers scope."
    pdf = {1: "Body ends here 2 Scope This section covers scope."}
    assert break_findings(_sec(l3), pdf) == []


def test_break_not_flagged_after_emphasised_full_stop():
    l3 = "Applies to *all users.*\n\nPolicy applies here today."
    pdf = {1: "Applies to all users. Policy applies here today."}
    assert break_findings(_sec(l3), pdf) == []


def test_break_not_flagged_around_unclosed_fence():
    l3 = "Intro text that goes on\n\n```\nand then more words follow here\n\nstill code here"
    pdf = {1: "Intro text that goes on and then more words follow here"}
    assert break_findings(_sec(l3), pdf) == []


def _units() -> list[SectionInput]:
    return [
        SectionInput("1", "A", 1, 2, "## 1 First\n\nbody"),
        SectionInput("2", "A", 3, 4, "## 2 Second\n\nbody\n\n### x1 Notes\n\nmore"),
        SectionInput("3", "A", 5, 5, "## 3 Third\n\nbody"),
    ]


def test_order_page_regression_flagged():
    secs = _units()
    secs[2] = SectionInput("3", "A", 2, 2, "## 3 Third\n\nbody")
    out = order_findings(secs, {}, {}, SectioningNotes())
    assert out == {"3": [Finding(kind="order", page=2, evidence={"other": "2"})]}


def test_order_title_positions_must_increase():
    pdf = {
        1: "Alpha Heading text here",
        2: "Beta Heading text here",
        3: "Gamma Heading text here",
    }
    secs = [
        SectionInput("1", "A", 1, 1, "x"),
        SectionInput("2", "A", 1, 3, "x"),
        SectionInput("3", "A", 1, 3, "x"),
    ]
    titles = {"1": "Alpha Heading", "2": "Gamma Heading", "3": "Beta Heading"}
    out = order_findings(secs, titles, pdf, SectioningNotes())
    assert out == {"3": [Finding(kind="order", page=1, evidence={"other": "2"})]}


def test_order_unrepaired_inversion_attached_to_enclosing_unit():
    notes = SectioningNotes(inversions=[Inversion(3, "x1", "x2", False)])
    secs = _units()
    secs[1] = SectionInput("2", "A", 3, 4, "## 2 Second\n\n### x1 A\n\n### x2 B\n")
    out = order_findings(secs, {}, {}, notes)
    assert out == {"2": [Finding(kind="order", page=3, evidence={"other": "x1"})]}


def test_order_repaired_inversion_not_flagged():
    notes = SectioningNotes(inversions=[Inversion(3, "2.1", "2.2", True)])
    assert order_findings(_units(), {}, {}, notes) == {}


def test_folded_fallback_reported_on_parent_unit():
    notes = SectioningNotes(fallbacks=[Fallback("x1", "Notes", 3)])
    out = fallback_findings(_units(), notes)
    assert out == {
        "2": [Finding(kind="fallback", page=3, evidence={"heading": "Notes"})]
    }


def test_front_matter_fallback_not_flagged():
    secs = [SectionInput("2", "front-matter", 3, 4, "### x1 Notes")]
    notes = SectioningNotes(fallbacks=[Fallback("x1", "Notes", 3)])
    assert fallback_findings(secs, notes) == {}


def test_part_root_fallback_not_flagged():
    secs = [SectionInput("appendix-a", "appendix-a", 3, 4, "### x1 Notes")]
    notes = SectioningNotes(fallbacks=[Fallback("x1", "Notes", 3)])
    assert fallback_findings(secs, notes) == {}


def test_fallback_inside_normal_appendix_unit_is_flagged():
    secs = [SectionInput("appendix-a.2", "appendix-a", 3, 4, "### x1 Notes")]
    notes = SectioningNotes(fallbacks=[Fallback("x1", "Notes", 3)])
    out = fallback_findings(secs, notes)
    assert list(out) == ["appendix-a.2"]


def test_enclosing_unit_maps_units_and_folded_ids():
    assert enclosing_unit(_units()) == {"1": "1", "2": "2", "x1": "2", "3": "3"}


def test_check_document_clean_doc_has_no_sections():
    secs = [SectionInput("1", "A", 1, 1, PAGE)]
    assert check_document(secs, {}, {1: PAGE}, {}, SectioningNotes()) == []


def test_check_document_reports_flagged_sections_with_digest():
    secs = [SectionInput("1", "A", 1, 1, PAGE)]
    pdf = {1: PAGE + " alpha bravo charlie delta echo foxtrot golf hotel"}
    out = check_document(secs, {}, pdf, {}, SectioningNotes())
    assert [s.id for s in out] == ["1"]
    assert out[0].l3_sha256 == quality.digest(PAGE)
    assert out[0].findings[0].kind == "content"


def test_check_document_unverifiable_skips_content():
    secs = [SectionInput("1", "A", 1, 1, PAGE)]
    out = check_document(secs, {}, {1: "  "}, {}, SectioningNotes())
    assert [f.kind for f in out[0].findings] == ["unverifiable"]


def test_check_document_drops_boundary_page_duplicates():
    extra = "alpha bravo charlie delta echo foxtrot golf hotel"
    secs = [
        SectionInput("1", "A", 1, 2, PAGE),
        SectionInput("2", "A", 2, 2, PAGE),
    ]
    pdf = {1: PAGE, 2: PAGE + " " + PAGE + " " + extra}
    out = check_document(secs, {}, pdf, {}, SectioningNotes())
    ids_with_extra = [
        s.id for s in out for f in s.findings if f.evidence.get("pdf") == extra
    ]
    assert ids_with_extra == ["1"]


_X = "alpha bravo charlie delta echo foxtrot golf hotel india juliet"
_Y = "kilo lima mike november oscar papa quebec romeo sierra tango"
_Z = "uniform victor whiskey xray yankee zulu amber bronze copper dune"


def test_check_document_three_units_sharing_a_boundary_page_are_clean():
    secs = [
        SectionInput("1", "A", 1, 2, _X),
        SectionInput("2", "A", 2, 2, _Y),
        SectionInput("3", "A", 2, 2, _Z),
    ]
    pdf = {1: _X, 2: _Y + " " + _Z}
    assert check_document(secs, {}, pdf, {}, SectioningNotes()) == []


def test_check_document_lost_text_after_a_later_heading_is_flagged_on_that_unit():
    lost = "vanished sentence about holding fixes and their radius limits"
    secs = [
        SectionInput("5", "A", 1, 2, "5.0 NAVIGATION DATA " + _X),
        SectionInput("6", "A", 2, 2, "6.0 ROUTES " + _Y),
    ]
    pdf = {1: "5.0 NAVIGATION DATA " + _X, 2: "6.0 ROUTES " + _Y + " " + lost}
    titles = {"5": "5.0 NAVIGATION DATA", "6": "6.0 ROUTES"}
    out = check_document(secs, titles, pdf, {}, SectioningNotes())
    assert [(c.id, [f.evidence for f in c.findings]) for c in out] == [
        ("6", [{"pdf": lost}])
    ]


def test_order_ignores_a_title_repeated_in_page_furniture():
    pdf = {2: "Beta Heading\nAlpha Heading intro text\nBeta Heading more text"}
    secs = [SectionInput("1", "A", 2, 2, "x"), SectionInput("2", "A", 2, 2, "x")]
    titles = {"1": "Alpha Heading", "2": "Beta Heading"}
    furniture = {2: ["Beta Heading"]}
    out = order_findings(secs, titles, pdf, SectioningNotes(), furniture)
    assert out == {}
