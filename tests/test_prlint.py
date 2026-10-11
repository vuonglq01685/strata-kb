"""Tests for prlint — the PR description gate. Pure text, no fixtures."""

from __future__ import annotations

from strata_kb.prlint import REQUIRED_SECTIONS, lint_body

_FENCE = "```\n12 passed in 0.4s\n```"


def _body(**overrides: str) -> str:
    """A passing description; override one section to make it fail."""
    filled = {
        "Ticket": "open-new-flight — add the new-flight endpoint",
        "Changes": "- flights/api.py: POST /flights",
        "Testing": f"AC1 → test_rejects_bad_icao\n\n{_FENCE}\n\nBlocking: No",
    }
    filled.update(overrides)
    return "\n\n".join(f"## {name}\n\n{filled[name]}" for name in REQUIRED_SECTIONS)


def _testing(fence: str) -> str:
    """A Testing section with a valid verdict, so only the fence is under test."""
    return f"{fence}\n\nBlocking: No"


def _codes(body: str) -> set[tuple[str, str]]:
    return {(f.section, f.code) for f in lint_body(body).findings}


def test_canon_is_ticket_changes_testing():
    assert REQUIRED_SECTIONS == ("Ticket", "Changes", "Testing")


def test_a_fully_filled_description_passes():
    report = lint_body(_body())
    assert report.passed, report.render()
    # No plan_dir given (default None) — the plan-dir-unset warning is
    # expected (see test_no_plan_dir_is_a_warning_not_a_failure); only
    # errors are pinned to zero here.
    assert report.errors == ()


def test_notes_is_optional_and_never_inspected():
    assert lint_body(_body()).passed
    assert lint_body(_body() + "\n\n## Notes\n\n<!-- nothing -->\n").passed
    assert lint_body(_body() + "\n\n## Notes\n\nOut of scope: refunds\n").passed


def test_an_old_nine_section_body_fails_on_the_new_canon():
    old = (
        "## Ticket\n\nATM-7\n\n## Verification\n\n```\nok\n```\n\n"
        "## Review\n\nBlocking: No"
    )
    codes = _codes(old)
    assert ("Changes", "missing-section") in codes
    assert ("Testing", "missing-section") in codes


def test_an_empty_body_reports_every_section_missing():
    report = lint_body("")
    assert not report.passed
    # Exact set: no plan_dir given, so a plan-dir-unset warning rides along
    # (see test_no_plan_dir_is_a_warning_not_a_failure) alongside the
    # missing-section errors this test pins — nothing else.
    assert _codes("") == {(name, "missing-section") for name in REQUIRED_SECTIONS} | {
        ("Testing", "plan-dir-unset")
    }


def test_a_missing_heading_is_reported_by_name():
    body = _body().replace("## Changes", "## Notes")
    assert ("Changes", "missing-section") in _codes(body)


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


def test_none_is_ordinary_content_outside_testing():
    # Nonsense, but not this linter's business: presence and non-emptiness
    # are all it checks outside `## Testing`.
    assert lint_body(_body(Ticket="none", Changes="none")).passed


def test_testing_prose_without_a_fence_is_rejected():
    body = _body(Testing=_testing("All tests pass and the linter is clean."))
    assert ("Testing", "no-verification-output") in _codes(body)


def test_testing_with_an_empty_fence_is_rejected():
    body = _body(Testing=_testing("```\n\n```"))
    assert ("Testing", "no-verification-output") in _codes(body)


def test_testing_accepts_a_tilde_fence_and_an_info_string():
    assert lint_body(_body(Testing=_testing("~~~text\n12 passed in 0.4s\n~~~"))).passed
    assert lint_body(
        _body(Testing=_testing("```console\n12 passed in 0.4s\n```"))
    ).passed


def test_output_hidden_inside_a_comment_does_not_count_as_evidence():
    body = _body(Testing="<!-- ```\n12 passed\n```\n\nBlocking: No -->")
    assert ("Testing", "empty-section") in _codes(body)


def test_output_hidden_by_a_comment_opened_on_the_heading_line_does_not_count_as_evidence():
    # Mirror of the test above: there the comment opens inside the section's
    # content; here it opens on the heading line itself. This pins the half
    # of the raw-append bug that opening it from the content side left
    # untouched — `_split_sections` used to append the RAW line once a
    # heading had matched, so a fence and its output that only ever existed
    # inside the still-open comment were captured as real content and read
    # as visible evidence.
    body = (
        _body(Testing=_testing(_FENCE)).replace(
            "## Testing\n\n```", "## Testing <!--\n\n```"
        )
        + "\n\n-->"
    )
    assert ("Testing", "empty-section") in _codes(body)


def test_a_heading_hidden_inside_a_balanced_comment_is_missing():
    # The gate's one fail-open path (regression pin): wrapping a whole
    # section in `<!-- -->` is the standard GitHub idiom for hiding
    # untouched template content, so an ordinary author reaches this. The
    # heading inside the comment must not open a section — the section
    # reads as missing, not as present and filled.
    body = _body().replace(
        "## Changes\n\n- flights/api.py: POST /flights",
        "<!--\n## Changes\n\n- flights/api.py: POST /flights\n-->",
    )
    assert ("Changes", "missing-section") in _codes(body)


def test_an_unterminated_comment_swallows_every_later_heading():
    # An unclosed `<!--` opened on its own line masks every later line to
    # "", so no later heading ever matches `_HEADING` at all — the later
    # sections read as missing. See
    # test_a_comment_opened_on_a_heading_line_swallows_the_rest for the pin
    # on the no-reset rule itself: this input never reaches the
    # confirmed-heading branch, so it can't catch a reset being restored
    # there.
    body = _body(Ticket="<!-- the ticket id goes here")
    assert ("Testing", "missing-section") in _codes(body)


def test_a_comment_opened_on_a_heading_line_swallows_the_rest():
    # Pins the "no reset on heading" rule itself: a heading line can also
    # open an unterminated comment (`## Changes <!-- note`), so the line
    # still matches `_HEADING` *and* leaves the comment open. That is the
    # only shape where a reset on the confirmed-heading branch would fire —
    # without this pin, such a reset could be silently restored and every
    # other test would stay green.
    body = _body().replace("## Changes", "## Changes <!-- note")
    assert ("Testing", "missing-section") in _codes(body)


def test_a_balanced_comment_inside_a_fence_is_a_no_op():
    # Control for the swallowing rule above: a fence's real content may
    # legitimately contain a balanced HTML comment (e.g. an aside next to
    # pasted output). That must parse as ordinary fence content and leave
    # the fence's own boundaries alone.
    body = _body(Testing=_testing("```\n<!-- oops -->\n12 passed\n```"))
    assert lint_body(body).passed


def test_an_unbalanced_comment_inside_a_fence_fails_closed():
    # Same rule from the other direction: an unclosed `<!--` started inside
    # a fence never lets that fence close either, so it swallows the rest of
    # the body exactly as an unbalanced fence does on its own.
    body = (
        _body(Testing=_testing("```\n<!-- oops\n12 passed\n```")) + "\n\n## Notes\n\nx"
    )
    assert not lint_body(body).passed


def test_a_duplicate_heading_is_reported():
    body = _body() + "\n\n## Changes\n\nagain\n"
    assert ("Changes", "duplicate-section") in _codes(body)


def test_a_heading_inside_a_fence_is_content_not_a_section():
    # A PR that pastes markdown into its test block must not have that paste
    # read as a second `## Changes` section.
    body = _body(Testing=_testing("```\n## Changes\n12 passed in 0.4s\n```"))
    assert lint_body(body).passed


def test_an_unbalanced_fence_fails_closed_not_open():
    # A stray opening fence swallows the rest of the body, so what follows it
    # is never read. That is the safe direction — CI goes red and the author
    # fixes the fence; it can never let an unfilled description through.
    body = _body(Changes="```\n- flights/api.py")
    assert not lint_body(body).passed
    assert ("Testing", "missing-section") in _codes(body)


def test_crlf_input_is_handled():
    assert lint_body(_body().replace("\n", "\r\n")).passed


def test_a_leading_utf8_bom_does_not_hide_the_ticket_heading():
    # `read_text(encoding="utf-8")` leaves a UTF-8 BOM as a leading U+FEFF,
    # which otherwise stops `_HEADING` matching the very first line and
    # reports the misleading "no '## Ticket' heading".
    assert lint_body("﻿" + _body()).passed


def test_trailing_whitespace_after_a_heading_is_tolerated():
    assert lint_body(_body().replace("## Ticket", "## Ticket   ")).passed


def test_a_deeper_heading_does_not_end_a_section():
    body = _body(Testing=_testing("### Suite\n\n```\n12 passed\n```"))
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


from strata_kb.prlint import Finding, PRLintReport


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

from strata_kb.prlint import plan_cmd_test, ticket_id_of


def _plan(tmp_path: Path, ticket: str = "ATM-7", cmd: str = "pytest -q") -> Path:
    d = tmp_path / "docs" / "impl"
    (d / ticket).mkdir(parents=True)
    (d / ticket / "plan.md").write_text(
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


def test_ticket_id_reads_a_mission_user_story_id():
    assert (
        ticket_id_of("M-myflix-search-US2 — search by title") == "M-myflix-search-US2"
    )
    assert ticket_id_of("M-x1-US10") == "M-x1-US10"


def test_plan_cmd_test_reads_the_header_line_and_strips_backticks(tmp_path: Path):
    d = _plan(tmp_path)
    assert plan_cmd_test(d, "ATM-7") == "pytest -q"
    assert plan_cmd_test(d, "ATM-8") is None


def test_testing_fence_holding_cmd_test_passes(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Testing=_testing("```\n$ pytest -q\n12 passed in 0.4s\n```"))
    report = lint_body(body, plan_dir=d)
    assert report.passed, report.render()
    assert report.warnings == ()


def test_testing_fence_without_cmd_test_is_an_error(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Testing=_testing("```\n12 passed in 0.4s\n```"))
    report = lint_body(body, plan_dir=d)
    assert not report.passed
    (f,) = [f for f in report.errors if f.code == "verification-missing-cmd"]
    assert f.section == "Testing"
    assert "pytest -q" in f.message and "plan.md" in f.message and "ATM-7" in f.message


def test_cmd_test_in_prose_outside_the_fence_does_not_count(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Testing=_testing("ran pytest -q\n\n```\n12 passed\n```"))
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
    (d / "ATM-7").mkdir(parents=True)
    (d / "ATM-7" / "plan.md").write_text("# plan\n\nstatus: draft\n", encoding="utf-8")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    assert [f.code for f in report.warnings] == ["cmd-test-unset"]


def test_a_non_utf8_plan_file_is_a_warning_not_a_crash(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    (d / "ATM-7").mkdir(parents=True)
    (d / "ATM-7" / "plan.md").write_bytes(b"# plan\n\ncmd.test: \xff\xfe pytest -q\n")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-missing"]


def test_flat_plan_is_plan_missing_with_a_tidy_hint(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ATM-7-plan.md").write_text("cmd.test: `pytest -q`\n", encoding="utf-8")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    (f,) = report.warnings
    assert f.code == "plan-missing"
    assert "kb impl tidy" in f.message


def _verdict(text: str) -> str:
    """A Testing section with a valid fence, so only the verdict is under test."""
    return f"{_FENCE}\n\n{text}"


def test_a_clean_review_passes():
    assert lint_body(_body()).passed


def test_testing_without_a_verdict_line_fails():
    body = _body(Testing=_verdict("Looks fine to me."))
    assert ("Testing", "no-review-verdict") in _codes(body)


def test_none_does_not_satisfy_the_verdict():
    # A clean review still states its verdict.
    assert ("Testing", "no-review-verdict") in _codes(_body(Testing=_verdict("none")))


def test_a_blocking_review_fails_the_pr():
    body = _body(Testing=_verdict("Blocking: Yes"))
    assert ("Testing", "review-blocking") in _codes(body)
    assert not lint_body(body).passed


def test_the_verdict_line_is_case_insensitive():
    assert lint_body(_body(Testing=_verdict("blocking: no"))).passed


def test_a_second_blocking_yes_fails_even_after_a_leading_blocking_no():
    # Fail-closed: leftover template boilerplate (`Blocking: No`) above the
    # author's own verdict must not shadow a real `Blocking: Yes` below it.
    body = _body(Testing=_verdict("Blocking: No\n\nBlocking: Yes"))
    assert ("Testing", "review-blocking") in _codes(body)
    assert not lint_body(body).passed


def test_the_word_blocking_in_a_sentence_is_not_a_verdict_line():
    # The verdict pattern is anchored at line start so a sentence merely
    # mentioning the word cannot pass for a recorded verdict.
    body = _body(Testing=_verdict("Nothing here is blocking: no big deal"))
    assert ("Testing", "no-review-verdict") in _codes(body)


def test_an_unclosed_fence_in_testing_fails_even_with_nothing_after_it():
    # Testing is the last required section, so a stray fence there swallows
    # only the optional Notes — the gate must still go red, not pass on a
    # body whose fence never closed.
    body = _body(Testing="```\n12 passed\n\nBlocking: No")
    assert ("Testing", "unclosed-fence") in _codes(body)
    assert not lint_body(body + "\n\n## Notes\n\nx").passed


def test_an_optional_usage_section_passes_with_or_without_content():
    # 1.16.0 (review B4): `## Usage` is allowed, never required.
    from strata_kb.prlint import lint_body as _lint_pr

    base = (
        "## Ticket\n\nT-7 add search.\n\n## Changes\n\n- search box\n\n"
        "## Testing\n\nAC1 -> test_search\n\n```\n$ pytest -q\n3 passed\n```\n\n"
        "Blocking: No\n"
    )
    usage = "\n## Usage\n\nTotal for T-7: 4 calls, 1,040 tokens, 0.01 USD.\n"
    assert _lint_pr(base).passed
    assert _lint_pr(base + usage).passed
