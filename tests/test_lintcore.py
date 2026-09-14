"""Tests for the shared lint primitives — specifically the notes channel,
which records checks that could not run, and `check_diagram`'s line-start
keyword anchoring. Ticket/mission behaviour is covered by their own suites.
"""

from __future__ import annotations

import pytest

from center_kb import lintcore
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


# --- check_headings / citations: HTML comments are not content ---


def test_check_headings_ignores_a_heading_inside_a_comment():
    """BEFORE: only fences were stripped, so four required sections could
    be commented out and the gate still passed (reviewer E's G5). AFTER:
    comments are stripped first — they are invisible in the rendered
    document, so a heading inside one is not present."""
    text = (
        "# Ticket\n"
        "<!--\n"
        "## Summary\n"
        "hidden\n"
        "-->\n"
        "## User Story\n"
    )
    issues = check_headings(text, ("## Summary", "## User Story"))
    assert [i.message for i in issues] == [
        "missing required heading: '## Summary'"
    ]


def test_visible_body_strips_comments():
    assert lintcore.visible_body("<!-- guidance -->\n\nreal text\n") == (
        "real text"
    )
    assert lintcore.visible_body("<!-- only guidance -->\n") == ""


def test_citation_scan_text_drops_comments():
    """G6/G7: a citation that only exists inside a comment is neither a
    citation nor an error."""
    scanned = lintcore.citation_scan_text(
        "body text\n<!-- TODO check arinc-424 §9.999 later -->\n"
    )
    assert "9.999" not in scanned
    assert "body text" in scanned


# --- section_body: fences do not terminate a section ---


def test_section_body_ignores_a_hash_line_inside_a_fence():
    """BEFORE: `section_body` scanned raw lines for the next '# '/'## '
    line, so a bash comment inside a fenced example truncated the section
    and the AC check reported 'must have at least 1 - [ ] item' on a
    ticket that has two. AFTER: fence contents are blanked before the
    terminator scan, so the whole section comes back."""
    text = (
        "## Acceptance Criteria\n"
        "```bash\n"
        "# example invocation\n"
        "importer --file feed.dat\n"
        "```\n"
        "- [ ] AC1 — first\n"
        "- [ ] AC2 — second\n"
        "\n"
        "## Use cases\n"
        "content\n"
    )
    body = lintcore.section_body(text, "## Acceptance Criteria")
    assert "- [ ] AC1 — first" in body
    assert "- [ ] AC2 — second" in body
    assert "## Use cases" not in body


def test_section_body_returns_the_original_fence_text():
    """The blanking is a scanning view only — callers still receive the
    real text, or `check_diagram` would never find its mermaid fence."""
    text = (
        "## Sequence diagram\n"
        "```text\n"
        "# not a diagram\n"
        "```\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "  A->>B: go\n"
        "```\n"
    )
    body = lintcore.section_body(text, "## Sequence diagram")
    assert "sequenceDiagram" in body
    assert "# not a diagram" in body


def test_section_body_does_not_start_at_a_heading_inside_a_fence():
    """A heading pasted into a fenced example is not a section start —
    the same rule `check_headings` already applies to presence."""
    text = (
        "# Ticket\n"
        "```markdown\n"
        "## Summary\n"
        "pasted example body\n"
        "```\n"
        "## Summary\n"
        "the real summary\n"
    )
    assert lintcore.section_body(text, "## Summary").strip() == (
        "the real summary"
    )


def test_section_body_does_not_start_at_a_heading_inside_a_comment():
    text = (
        "# Ticket\n"
        "<!--\n"
        "## Summary\n"
        "commented-out guidance\n"
        "-->\n"
        "## Summary\n"
        "the real summary\n"
    )
    assert lintcore.section_body(text, "## Summary").strip() == (
        "the real summary"
    )


def test_section_body_still_returns_none_for_a_missing_heading():
    assert lintcore.section_body("# Ticket\n\nbody\n", "## Summary") is None


def test_section_body_survives_a_trailing_fence_with_no_final_newline():
    """BEFORE this fix: `_blank`'s replacement is always pure '\\n'
    characters, so it always ends in a newline. When the document's LAST
    fence touches EOF with no trailing newline (a file saved without one,
    or simply the last section in the ticket — e.g. `## Sequence
    diagram`'s mermaid fence), the blanked copy gains a newline the
    original never had and ends up one `splitlines()` entry SHORTER than
    the original. `len(scan) != len(lines)` then fired and `scan = lines`
    discarded the fence-aware scan for the WHOLE document, silently
    reproducing HIGH-3: the '# example invocation' comment inside the
    unrelated '## Acceptance Criteria' fence truncates that section again,
    even though neither the AC section nor its fence is the one missing a
    trailing newline. AFTER: a length SHORTFALL is padded with blank
    lines (proven to always be exactly one, always at the end) instead of
    discarding the scan."""
    text = (
        "## Acceptance Criteria\n"
        "```bash\n"
        "# example invocation\n"
        "importer --file feed.dat\n"
        "```\n"
        "- [ ] AC1 — first\n"
        "- [ ] AC2 — second\n"
        "\n"
        "## Sequence diagram\n"
        "```mermaid\n"
        "sequenceDiagram\n"
        "  A->>B: go\n"
        "```"
    )
    assert not text.endswith("\n")  # sanity: no trailing newline at EOF

    body = lintcore.section_body(text, "## Acceptance Criteria")

    assert "- [ ] AC1 — first" in body
    assert "- [ ] AC2 — second" in body


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


# --- new-template shared helpers (BA upgrade v2) ---

from center_kb.lintcore import (
    check_open_question_owners,
    check_recommended_sections,
    open_question_rows,
    table_rows,
)


def test_open_question_rows_none_when_heading_absent():
    assert open_question_rows("# T\n\n## Summary\nx\n") is None


def test_open_question_rows_extracts_checkbox_rows():
    text = (
        "# T\n\n## Open questions\n"
        "- [ ] Q1 — color token — owner: design — blocks: AC3\n"
        "- [x] Q2 — closed one — owner: ba\n"
        "not a row\n"
    )
    rows = open_question_rows(text)
    assert rows is not None and len(rows) == 2
    assert rows[0].startswith("Q1")


def test_check_open_question_owners_warns_per_ownerless_row():
    issues = check_open_question_owners(
        ["Q1 — who decides — owner: ba", "Q2 — nobody owns this"]
    )
    assert len(issues) == 1
    assert issues[0].level == "warning"
    assert "Q2" in issues[0].message


def test_check_recommended_sections_missing_and_empty():
    text = "# T\n\n## Dependencies\n\n## Out of scope\nEditing records.\n"
    issues = check_recommended_sections(
        text, ("## Dependencies", "## Out of scope", "## Open questions")
    )
    messages = [i.message for i in issues]
    assert all(i.level == "warning" for i in issues)
    assert any(
        "'## Dependencies' is empty" in m for m in messages
    )
    assert any(
        "recommended section missing: '## Open questions'" in m
        for m in messages
    )
    assert not any("Out of scope" in m for m in messages)


def test_check_recommended_sections_html_comment_only_body_is_empty():
    text = "# T\n\n## Dependencies\n<!-- guidance left in place -->\n"
    issues = check_recommended_sections(text, ("## Dependencies",))
    assert len(issues) == 1
    assert "empty" in issues[0].message


def test_check_recommended_sections_ignores_heading_inside_fence():
    text = "# T\n\n```\n## Dependencies\n```\n"
    issues = check_recommended_sections(text, ("## Dependencies",))
    assert len(issues) == 1
    assert "missing" in issues[0].message


def test_check_recommended_sections_ignores_heading_inside_comment():
    """The presence half's `present` set must agree with the emptiness
    half (already comment-blind, covered by
    `test_check_recommended_sections_html_comment_only_body_is_empty`) —
    a heading that exists only inside a comment is reported missing, not
    silently treated as present."""
    text = "# T\n\n<!--\n## Dependencies\n-->\n"
    issues = check_recommended_sections(text, ("## Dependencies",))
    assert len(issues) == 1
    assert "missing" in issues[0].message


def test_table_rows_parses_cells_and_drops_separators():
    body = (
        "| # | Decision | Status | Owner | Blocks |\n"
        "|---|---|---|---|---|\n"
        "| D1 | Storage engine | OPEN | tech-lead | M-x-US1 |\n"
    )
    rows = table_rows(body)
    assert rows[0][1] == "Decision"
    assert rows[1] == ["D1", "Storage engine", "OPEN", "tech-lead", "M-x-US1"]
    assert len(rows) == 2


# --- Review record (maturity review) ---


def test_check_review_record_warns_when_heading_missing():
    issues = lintcore.check_review_record("# T\n\n## Summary\nx\n")
    assert [i.level for i in issues] == ["warning"]
    assert "'## Review record' missing" in issues[0].message


def test_check_review_record_warns_on_untouched_placeholder():
    text = (
        "# T\n\n## Review record\n"
        "<!-- guidance -->\n"
        "Not yet reviewed.\n\n"
        "| Date | Round | Business | Dev | Reviewer |\n"
        "|---|---|---|---|---|\n"
    )
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["warning"]
    assert "placeholder" in issues[0].message


def test_check_review_record_warns_on_empty_body():
    text = "# T\n\n## Review record\n<!-- guidance only -->\n\n## Next\nx\n"
    issues = lintcore.check_review_record(text)
    assert [i.level for i in issues] == ["warning"]


def test_check_review_record_accepts_a_filled_record():
    text = (
        "# T\n\n## Review record\n"
        "| Date | Round | Business | Dev | Reviewer |\n"
        "|---|---|---|---|---|\n"
        "| 2026-08-12 | 1 | 4 | 4 | agent |\n\n"
        "Open gaps: none\n"
    )
    assert lintcore.check_review_record(text) == []


# --- Task 3: kb-context tags must exist on the federation ---


def test_check_context_tags_rejects_a_tag_no_document_publishes(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-tag"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert [i.level for i in issues] == ["error"]
    assert "ghost-tag" in issues[0].message
    assert "kb tags" in issues[0].message
    # Pin the two strongest wording constraints: without these, a reword
    # could silently drop the instruction that stops a BA from falsifying
    # the pinned `version:` by re-running `kb context new`.
    assert "kb context new" in issues[0].message
    assert "deleting the tag" in issues[0].message


def test_check_context_tags_accepts_a_published_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["airspace", "arinc424"],
    )

    assert lintcore.check_context_tags(ctx, HubHandle(root=fed_hub)) == []


def test_check_context_tags_ignores_casing(fed_hub):
    from center_kb.hub import HubHandle

    # searchdb lowercases tags when indexing, so a casing difference has no
    # downstream effect and must not cost a BA an edit.
    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["AirSpace"],
    )

    assert lintcore.check_context_tags(ctx, HubHandle(root=fed_hub)) == []


def test_check_context_tags_suggests_the_nearest_real_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["airspce"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert "airspace" in issues[0].message


def test_check_context_tags_reports_every_unknown_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-one", "airspace", "ghost-two"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert len(issues) == 2
    assert "ghost-one" in issues[0].message
    assert "ghost-two" in issues[1].message


def test_check_context_tags_is_silent_when_the_vocabulary_is_empty(fed_hub):
    """An empty vocabulary means the hub mirror is absent or unreadable —
    `federation.load_federation` returns no repos when `federation/` is
    missing, and silently skips any repo whose `index.yaml` fails to parse.
    That is not evidence every tag in the block was invented, so this must
    stay silent (the same epistemic position `check_context_block` already
    takes for `hub is None`), even at the cost of letting a genuinely
    fabricated tag through when the whole federation carries no tags.
    Built the way `test_cli.py::test_tags_on_a_kb_with_no_tags_exits_zero...`
    does: overwrite both fed_hub repos' index.yaml with an empty KBIndex."""
    from center_kb import models
    from center_kb.hub import HubHandle

    for rid in ("arinc-kb", "icao-kb"):
        models.save_yaml_model(
            fed_hub / "federation" / rid / "index.yaml", models.KBIndex()
        )

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-tag"],
    )

    assert lintcore.check_context_tags(ctx, HubHandle(root=fed_hub)) == []


def test_check_context_tags_message_names_the_incomplete_mirror_possibility(
    fed_hub,
):
    """A *partially* broken mirror (one corrupt repo among healthy ones)
    cannot be told apart from a real typo — the vocabulary is simply
    missing that repo's tags, with no signal left behind. The message must
    therefore name that possibility rather than assert the tag was
    fabricated."""
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-tag"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert "index.yaml" in issues[0].message
    assert "incomplete" in issues[0].message


def test_check_context_tags_incomplete_mirror_caveat_appears_once(fed_hub):
    """`Report.render` emits one line per issue, so the ~300-character
    incomplete-mirror caveat must not repeat per bad tag — it belongs on
    the first issue only; later issues keep the short form (tag, hint,
    `kb tags`, fix instruction)."""
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-one", "ghost-two"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert len(issues) == 2
    assert "index.yaml" in issues[0].message
    assert "incomplete" in issues[0].message
    assert "index.yaml" not in issues[1].message
    assert "incomplete" not in issues[1].message
    # The short form is still complete on the second issue.
    assert "ghost-two" in issues[1].message
    assert "kb tags" in issues[1].message
    assert "kb context new" in issues[1].message


def test_check_context_block_skips_the_tag_check_without_a_hub():
    # No hub means no vocabulary, so no conclusion about a tag is possible.
    # The unreachable hub is already its own error; do not pile on.
    text = (
        'kb-context:\n  version: "abc1234"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n  tags: [ghost-tag]\n"
    )

    issues, ctx = lintcore.check_context_block(text, None)

    assert ctx is not None and ctx.tags == ["ghost-tag"]
    assert all("ghost-tag" not in i.message for i in issues)
