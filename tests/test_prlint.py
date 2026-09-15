"""Tests for prlint — the PR description gate. Pure text, no fixtures."""

from __future__ import annotations

from center_kb.prlint import (
    REQUIRED_SECTIONS,
    SENTINEL_SECTIONS,
    lint_body,
)


def _body(**overrides: str) -> str:
    """A passing description; override one section to make it fail."""
    filled = {
        "Ticket": "open-new-flight — add the new-flight endpoint",
        "kb-context": "arinc-kb:arinc-424 §5.3 @ 4f2a91c",
        "AC→test map": "AC1 → tests/test_flight.py::test_rejects_bad_icao",
        "Placeholder resolutions": "<max-alt> → 45000 per ATM-STD §5.3",
        "Verification": "```\n12 passed in 0.4s\n```",
        "TDD exemptions": "none",
        "Findings": "none",
        "Usage": "| phase | cost |\n|---|---|\n| dev-execute | $1.20 |",
    }
    filled.update(overrides)
    return "\n\n".join(f"## {name}\n\n{filled[name]}" for name in REQUIRED_SECTIONS)


def _codes(body: str) -> set[tuple[str, str]]:
    return {(f.section, f.code) for f in lint_body(body).findings}


def test_canon_is_the_eight_sections_in_order():
    assert REQUIRED_SECTIONS == (
        "Ticket",
        "kb-context",
        "AC→test map",
        "Placeholder resolutions",
        "Verification",
        "TDD exemptions",
        "Findings",
        "Usage",
    )
    assert SENTINEL_SECTIONS == frozenset({"TDD exemptions", "Findings"})


def test_a_fully_filled_description_passes():
    report = lint_body(_body())
    assert report.passed, report.render()
    # No plan_dir given (default None) — the plan-dir-unset warning is
    # expected (see test_no_plan_dir_is_a_warning_not_a_failure); only
    # errors are pinned to zero here.
    assert report.errors == ()


def test_an_empty_body_reports_every_section_missing():
    report = lint_body("")
    assert not report.passed
    # Exact set: no plan_dir given, so a plan-dir-unset warning rides along
    # (see test_no_plan_dir_is_a_warning_not_a_failure) alongside the eight
    # missing-section errors this test pins — nothing else.
    assert _codes("") == {
        (name, "missing-section") for name in REQUIRED_SECTIONS
    } | {("Verification", "plan-dir-unset")}


def test_a_missing_heading_is_reported_by_name():
    body = _body().replace("## Usage", "## Notes")
    assert ("Usage", "missing-section") in _codes(body)


def test_a_section_holding_only_an_html_comment_is_empty():
    # The load-bearing rule: an untouched template is all comments, so
    # without this the shipped template would pass and the gate would be
    # decoration.
    body = _body(Ticket="<!-- the ticket id goes here -->")
    assert ("Ticket", "empty-section") in _codes(body)


def test_a_multiline_html_comment_is_stripped_too():
    body = _body(Ticket="<!--\nthe ticket id\ngoes here\n-->")
    assert ("Ticket", "empty-section") in _codes(body)


def test_an_unterminated_html_comment_fails_closed():
    body = _body(Ticket="<!-- the ticket id goes here")
    assert ("Ticket", "empty-section") in _codes(body)


def test_none_is_a_valid_answer_in_the_two_sentinel_sections():
    for section in SENTINEL_SECTIONS:
        assert lint_body(_body(**{section: "none"})).passed
        assert lint_body(_body(**{section: "`None`"})).passed
        assert lint_body(_body(**{section: "_none_"})).passed


def test_none_elsewhere_is_ordinary_content_not_an_error():
    # Nonsense, but not this linter's business: presence and non-emptiness
    # are all it checks outside `## Verification`.
    assert lint_body(_body(Ticket="none")).passed


def test_verification_prose_without_a_fence_is_rejected():
    body = _body(Verification="All tests pass and the linter is clean.")
    assert ("Verification", "no-verification-output") in _codes(body)


def test_verification_with_an_empty_fence_is_rejected():
    body = _body(Verification="```\n\n```")
    assert ("Verification", "no-verification-output") in _codes(body)


def test_verification_accepts_a_tilde_fence_and_an_info_string():
    body = _body(Verification="~~~text\n12 passed in 0.4s\n~~~")
    assert lint_body(body).passed
    body = _body(Verification="```console\n12 passed in 0.4s\n```")
    assert lint_body(body).passed


def test_output_hidden_inside_a_comment_does_not_count_as_evidence():
    body = _body(Verification="<!-- ```\n12 passed\n``` -->")
    assert ("Verification", "empty-section") in _codes(body)


def test_output_hidden_by_a_comment_opened_on_the_heading_line_does_not_count_as_evidence():
    # Mirror of the test above: there the comment opens inside the section's
    # content; here it opens on the heading line itself. This pins the half
    # of the raw-append bug that opening it from the content side left
    # untouched — `_split_sections` used to append the RAW line once a
    # heading had matched, so a fence and its output that only ever existed
    # inside the still-open comment were captured as real content and read
    # as visible evidence.
    body = _body().replace(
        "## Verification\n\n```\n12 passed in 0.4s\n```",
        "## Verification <!--\n\n```\n12 passed in 0.4s\n```\n\n-->",
    )
    assert ("Verification", "empty-section") in _codes(body)


def test_a_heading_hidden_inside_a_balanced_comment_is_missing():
    # The gate's one fail-open path (regression pin): wrapping a whole
    # section in `<!-- -->` is the standard GitHub idiom for hiding
    # untouched template content, so an ordinary author reaches this. The
    # heading inside the comment must not open a section — the section
    # reads as missing, not as present and filled.
    body = _body().replace(
        "## TDD exemptions\n\nnone", "<!--\n## TDD exemptions\n\nnone\n-->"
    )
    assert ("TDD exemptions", "missing-section") in _codes(body)


def test_an_unterminated_comment_swallows_every_later_heading():
    # An unclosed `<!--` opened on its own line masks every later line to
    # "", so no later heading ever matches `_HEADING` at all — the later
    # sections read as missing. See
    # test_a_comment_opened_on_a_heading_line_swallows_the_rest for the pin
    # on the no-reset rule itself: this input never reaches the
    # confirmed-heading branch, so it can't catch a reset being restored
    # there.
    body = _body(Ticket="<!-- the ticket id goes here")
    assert ("Usage", "missing-section") in _codes(body)


def test_a_comment_opened_on_a_heading_line_swallows_the_rest():
    # Pins the "no reset on heading" rule itself: a heading line can also
    # open an unterminated comment (`## Verification <!-- note`), so the
    # line still matches `_HEADING` *and* leaves the comment open. That is
    # the only shape where a reset on the confirmed-heading branch would
    # fire — without this pin, such a reset could be silently restored and
    # every other test would stay green.
    body = _body().replace("## Verification", "## Verification <!-- note")
    assert ("Usage", "missing-section") in _codes(body)


def test_a_balanced_comment_inside_a_fence_is_a_no_op():
    # Control for the swallowing rule above: a fence's real content may
    # legitimately contain a balanced HTML comment (e.g. an aside next to
    # pasted output). That must parse as ordinary fence content and leave
    # the fence's own boundaries alone.
    body = _body(Verification="```\n<!-- oops -->\n12 passed\n```")
    assert lint_body(body).passed


def test_an_unbalanced_comment_inside_a_fence_fails_closed():
    # Same rule from the other direction: an unclosed `<!--` started inside
    # a fence never lets that fence close either, so it swallows the rest of
    # the body exactly as an unbalanced fence does on its own.
    body = _body(Verification="```\n<!-- oops\n12 passed\n```")
    assert not lint_body(body).passed
    assert ("Usage", "missing-section") in _codes(body)


def test_a_duplicate_heading_is_reported():
    body = _body() + "\n\n## Usage\n\nagain\n"
    assert ("Usage", "duplicate-section") in _codes(body)


def test_a_heading_inside_a_fence_is_content_not_a_section():
    # A PR that pastes markdown into its verification block must not have
    # that paste read as a second `## Usage` section.
    body = _body(Verification="```\n## Usage\n12 passed in 0.4s\n```")
    assert lint_body(body).passed


def test_an_unbalanced_fence_fails_closed_not_open():
    # A stray opening fence swallows the rest of the body, so the sections
    # after it read as missing. That is the safe direction — CI goes red and
    # the author fixes the fence; it can never let an unfilled description
    # through.
    body = _body(Verification="```\n12 passed in 0.4s")
    assert not lint_body(body).passed
    assert ("Usage", "missing-section") in _codes(body)


def test_crlf_input_is_handled():
    assert lint_body(_body().replace("\n", "\r\n")).passed


def test_a_leading_utf8_bom_does_not_hide_the_ticket_heading():
    # `read_text(encoding="utf-8")` leaves a UTF-8 BOM as a leading U+FEFF,
    # which otherwise stops `_HEADING` matching the very first line and
    # reports the misleading "no '## Ticket' heading".
    assert lint_body("\ufeff" + _body()).passed


def test_trailing_whitespace_after_a_heading_is_tolerated():
    assert lint_body(_body().replace("## Ticket", "## Ticket   ")).passed


def test_a_deeper_heading_does_not_end_a_section():
    body = _body(Verification="### Suite\n\n```\n12 passed\n```")
    assert lint_body(body).passed


def test_the_ascii_arrow_spelling_is_accepted():
    body = _body().replace("## AC→test map", "## AC->test map")
    assert lint_body(body).passed


def test_render_names_the_failing_sections_and_to_json_round_trips():
    report = lint_body("")
    text = report.render()
    assert "FAIL" in text
    for name in REQUIRED_SECTIONS:
        assert name in text
    payload = report.to_json()
    assert payload["passed"] is False
    assert len(report.errors) == len(REQUIRED_SECTIONS)
    assert payload["findings"][0]["code"] == "missing-section"
    # No plan_dir given, so the payload also carries the plan-dir-unset
    # warning; passed stays True and it is the only non-error finding.
    filled_payload = lint_body(_body()).to_json()
    assert filled_payload["passed"] is True
    assert all(f["level"] == "warning" for f in filled_payload["findings"])


from center_kb.prlint import EXEMPTION_SLUGS, Finding, PRLintReport


def test_the_four_exemption_slugs_are_the_canon():
    assert EXEMPTION_SLUGS == frozenset({"config", "ci", "docs", "style"})


def test_exemption_lines_naming_a_known_slug_pass():
    body = _body(**{"TDD exemptions": (
        "- config: ruff.toml — verified by running `ruff check .`\n"
        "- docs — README only, rendered locally\n"
        "Exempt: ci — verified by the workflow's own run on this PR\n"
        "- `style`: renames, suite green before and after"
    )})
    assert lint_body(body).passed


def test_none_still_passes_the_exemption_section():
    assert lint_body(_body(**{"TDD exemptions": "None."})).passed


def test_an_unknown_exemption_class_is_an_error():
    report = lint_body(_body(**{"TDD exemptions": "Exempt: deadline"}))
    assert not report.passed
    (f,) = [f for f in report.findings if f.section == "TDD exemptions"]
    assert f.code == "unknown-exemption-class"
    assert f.level == "error"
    for slug in ("config", "ci", "docs", "style"):
        assert slug in f.message


def test_prose_in_the_exemption_section_is_an_error():
    body = _body(**{"TDD exemptions": "we skipped tests because it was late"})
    assert ("TDD exemptions", "unknown-exemption-class") in _codes(body)


def test_a_warning_level_finding_does_not_fail_the_report():
    report = PRLintReport((Finding("Ticket", "x", "y", level="warning"),))
    assert report.passed
    assert report.warnings == report.findings
    assert report.errors == ()
    assert "warning" in report.render()
    assert report.to_json()["findings"][0]["level"] == "warning"


def test_findings_default_to_error_level():
    assert Finding("Ticket", "x", "y").level == "error"


from pathlib import Path

from center_kb.prlint import plan_cmd_test, ticket_id_of


def _plan(tmp_path: Path, ticket: str = "ATM-7", cmd: str = "pytest -q") -> Path:
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / f"{ticket}-plan.md").write_text(
        f"# {ticket} plan\n\ncmd.test: `{cmd}`\ncmd.lint: ruff check .\nstatus: approved\n",
        encoding="utf-8",
    )
    return d


def _ticket_body(**overrides: str) -> str:
    return _body(Ticket="ATM-7 — add the new-flight endpoint", **overrides)


def test_ticket_id_is_the_first_upper_dash_number_token():
    assert ticket_id_of("ATM-7 — add the endpoint") == "ATM-7"
    assert ticket_id_of("see PROJ-10 and PROJ-2") == "PROJ-10"
    assert ticket_id_of("open-new-flight — no id here") is None


def test_plan_cmd_test_reads_the_header_line_and_strips_backticks(tmp_path: Path):
    d = _plan(tmp_path)
    assert plan_cmd_test(d, "ATM-7") == "pytest -q"
    assert plan_cmd_test(d, "ATM-8") is None


def test_verification_fence_holding_cmd_test_passes(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="```\n$ pytest -q\n12 passed in 0.4s\n```")
    report = lint_body(body, plan_dir=d)
    assert report.passed, report.render()
    assert report.warnings == ()


def test_verification_fence_without_cmd_test_is_an_error(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="```\n12 passed in 0.4s\n```")
    report = lint_body(body, plan_dir=d)
    assert not report.passed
    (f,) = [f for f in report.errors if f.code == "verification-missing-cmd"]
    assert "pytest -q" in f.message and "ATM-7-plan.md" in f.message


def test_cmd_test_in_prose_outside_the_fence_does_not_count(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="ran pytest -q\n\n```\n12 passed\n```")
    assert not lint_body(body, plan_dir=d).passed


def test_no_plan_dir_is_a_warning_not_a_failure():
    report = lint_body(_ticket_body())
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-dir-unset"]


def test_unparsed_ticket_id_is_a_warning(tmp_path: Path):
    report = lint_body(_body(), plan_dir=_plan(tmp_path))
    assert report.passed
    assert [f.code for f in report.warnings] == ["ticket-id-unparsed"]


def test_missing_plan_file_is_a_warning(tmp_path: Path):
    report = lint_body(_ticket_body(), plan_dir=tmp_path / "nowhere")
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-missing"]


def test_plan_without_a_cmd_test_line_is_a_warning(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ATM-7-plan.md").write_text("# plan\n\nstatus: draft\n", encoding="utf-8")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    assert [f.code for f in report.warnings] == ["cmd-test-unset"]


def test_a_non_utf8_plan_file_is_a_warning_not_a_crash(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ATM-7-plan.md").write_bytes(b"# plan\n\ncmd.test: \xff\xfe pytest -q\n")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-missing"]
