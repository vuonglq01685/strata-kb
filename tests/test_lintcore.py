"""Tests for the shared lint primitives — specifically the notes channel,
which records checks that could not run, and `check_diagram`'s line-start
keyword anchoring. Ticket/mission behaviour is covered by their own suites.
"""

from __future__ import annotations

import pytest

from center_kb.doctor import Issue
from center_kb.kbcontext import KBContext, KBRef
from center_kb.lintcore import (
    INLINE_CITE_RE,
    LintReport,
    check_citation_consistency,
    check_diagram,
    check_headings,
)


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


# --- check_headings: fenced headings do not count as present ---


def test_check_headings_ignores_a_heading_inside_a_fence():
    """BEFORE this fix, `check_headings` scanned every line of the raw
    text, so a required heading pasted inside a fenced code block (e.g. a
    reference document quoted as a worked example) satisfied the presence
    check with no real section anywhere in the document. AFTER: fences are
    stripped first (mirroring `citation_scan_text`'s idiom), so the same
    document now reports the heading missing."""
    text = (
        "# Title\n\n"
        "```markdown\n"
        "## Business goal\n"
        "```\n"
    )

    issues = check_headings(text, ("## Business goal",))

    assert len(issues) == 1
    assert issues[0].level == "error"
    assert "## Business goal" in issues[0].message


def test_check_headings_finds_a_real_heading_outside_a_fence():
    """The normal case — an unfenced heading — must be unaffected by the
    fence-stripping fix."""
    text = "# Title\n\n## Business goal\n\nReal content here.\n"

    issues = check_headings(text, ("## Business goal",))

    assert issues == []


def test_check_headings_still_reports_a_genuinely_missing_heading():
    text = "# Title\n\nNo headings at all.\n"

    issues = check_headings(text, ("## Business goal",))

    assert len(issues) == 1
    assert "## Business goal" in issues[0].message


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


# --- INLINE_CITE_RE: sentence-ending punctuation ---


def test_inline_cite_re_drops_a_sentence_ending_period_from_the_section_id():
    """A citation at the end of a sentence ('... per arinc-424 §5.3.') must
    not absorb the period into the section id — otherwise an ordinary,
    correctly-pinned citation is reported as unresolved just because it
    happens to end the sentence."""
    text = "Airspace records follow arinc-kb:arinc-424 §5.3."

    (match,) = list(INLINE_CITE_RE.finditer(text))

    assert match.groups() == ("arinc-kb", "arinc-424", "5.3")


def test_inline_cite_re_keeps_a_multi_level_section_id_intact():
    """A multi-level section id ('§5.3.2') has internal periods that are
    NOT sentence punctuation — those must be kept.

    Note: this is NOT a regression test for the trailing-period bug — the
    pre-fix pattern ('[^\\s,;)\\]]+') already passed this exact case, since
    only a *trailing* period was ever the problem, not an internal one.
    What this test does guard against is the naive over-correction of
    simply dropping '.' from the excluded-character class altogether,
    which would have broken this case instead of fixing the real one."""
    text = "arinc-424 §5.3.2"

    (match,) = list(INLINE_CITE_RE.finditer(text))

    assert match.groups() == (None, "arinc-424", "5.3.2")


def test_inline_cite_re_drops_a_trailing_colon_from_the_section_id():
    """A citation immediately followed by a colon ('§5.3:') must not
    absorb the colon into the section id.

    This does not by itself discriminate this fix from the over-anchored
    '01e4ac2' pattern (both require an alnum on the trailing side after
    backtracking, so both get this right) — it pins coverage the previous
    suite lacked. See the non-alnum-initial test below for the case that
    DOES discriminate the two."""
    text = "arinc-424 §5.3: see the table"

    (match,) = list(INLINE_CITE_RE.finditer(text))

    assert match.groups() == (None, "arinc-424", "5.3")


def test_inline_cite_re_drops_a_trailing_question_mark_from_the_section_id():
    """A citation immediately followed by a question mark ('§5.3?') must
    not absorb it into the section id — same rationale as the trailing-
    colon case above."""
    text = "Does arinc-424 §5.3? Check the table."

    (match,) = list(INLINE_CITE_RE.finditer(text))

    assert match.groups() == (None, "arinc-424", "5.3")


def test_inline_cite_re_matches_a_non_alnum_initial_section_id():
    """A section id that does NOT start on an alnum ('§(a)') must still
    match — kbcontext._REF_RE's section-id half accepts any non-whitespace
    token ('\\S+'), so ids like this are legal to pin.

    This is the case that discriminates a tail-only anchor from the
    over-anchored '01e4ac2' pattern (which additionally required
    '[A-Za-z0-9]' as the FIRST character of the section id): anchoring the
    leading character would make '§(a)' fail to match at all, which is
    worse than the original bug — the citation silently disappears from
    view instead of being mis-parsed."""
    text = "arinc-424 §(a) applies here"

    (match,) = list(INLINE_CITE_RE.finditer(text))

    assert match.groups() == (None, "arinc-424", "(a")


# --- INLINE_CITE_RE / check_citation_consistency: nested repo qualifiers ---


def test_citation_consistency_accepts_a_nested_repo_qualifier():
    """`kbcontext._REF_RE` accepts nested path repo-ids ('mid/repo-x') for
    multi-tier federation. `INLINE_CITE_RE`'s repo group must mirror that —
    otherwise a body citation like 'mid/repo-x:doc-a §1.1' mis-parses (the
    'mid/' segment is silently dropped, leaving repo='repo-x'), and a
    correctly-pinned citation is wrongly reported as not in kb-context
    refs."""
    text = "See mid/repo-x:doc-a §1.1 for details."
    ctx = KBContext(
        version="1",
        refs=[KBRef(doc_id="doc-a", section_id="1.1", repo_id="mid/repo-x")],
    )

    issues = check_citation_consistency(text, ctx)

    assert issues == []


def test_citation_consistency_still_matches_a_flat_repo_qualifier():
    """Negative lock: a flat (non-nested) repo qualifier must keep working
    exactly as before — the widened repo group must not change single-
    segment behaviour."""
    text = "See repo-x:doc-a §1.1 for details."
    ctx = KBContext(
        version="1",
        refs=[KBRef(doc_id="doc-a", section_id="1.1", repo_id="repo-x")],
    )

    issues = check_citation_consistency(text, ctx)

    assert issues == []
