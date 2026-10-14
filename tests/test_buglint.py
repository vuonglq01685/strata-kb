"""Tests for the bug/hotfix lint (`buglint.py`) and its dispatch from
`ticketlint.lint`. Hermetic: bugs carry no `## KB context` by default, so
no hub is needed except in the one test that adds the block."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import buglint, ticket, ticketlint

_PNG = b"\x89PNG\r\n\x1a\n"

_SECTIONS: dict[str, str] = {
    "## Summary": "Export button returns 500 for accounts with no invoices.",
    "## Environment": "production, build 4.2.1, Chrome 126 on macOS, role admin.",
    "## Pre-conditions": "Logged in as admin; account has zero invoices.",
    "## Steps to reproduce": "1. Open Billing.\n2. Click Export.",
    "## Expected result": "A CSV with only the header row downloads.",
    "## Actual result": "HTTP 500, toast shows 'Internal error 0x42'.",
    "## Attachments": "![toast](BUG-12/toast.png)",
    "## Impact": "All new accounts, every export; workaround: add an invoice.",
    "## Open questions": "- [ ] Q1 — Is the 500 logged? — owner: ops — blocks: triage",
    "## Definition of Ready": (
        "- [ ] Steps reproduce the actual result on the stated environment\n"
        "- [ ] Every open question has an owner"
    ),
}


def _bug(
    *,
    type_: str | None = "bug",
    severity: str | None = "S2",
    related: str | None = "none",
    parent: str | None = None,
    revision: str | None = "1",
    title: str = "# BUG-12 — Export returns 500 on empty account",
    skip: tuple[str, ...] = (),
    override: dict[str, str] | None = None,
    extra: str = "",
) -> str:
    headers = []
    if type_ is not None:
        headers.append(f"> Type: {type_}")
    if severity is not None:
        headers.append(f"> Severity: {severity}")
    if revision is not None:
        headers.append(f"> Revision: {revision}")
    if related is not None:
        headers.append(f"> Related ticket: {related}")
    if parent is not None:
        headers.append(f"> Parent mission: {parent}")
    sections = {**_SECTIONS, **(override or {})}
    body = "\n\n".join(f"{h}\n{b}" for h, b in sections.items() if h not in skip)
    return title + "\n" + "\n".join(headers) + "\n\n" + body + "\n" + extra


def _errors(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "error"]


def _warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


def _lint(text: str, **kw):
    return ticketlint.lint(text, None, **kw)


def _bug_file(tmp_path: Path, text: str, *, image: bool = True) -> Path:
    folder = tmp_path / "tickets" / "bugs"
    (folder / "BUG-12").mkdir(parents=True)
    if image:
        (folder / "BUG-12" / "toast.png").write_bytes(_PNG)
    path = folder / "BUG-12.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- ticket.py contract ---


def test_ticket_type_defaults_to_story_and_lowercases():
    assert ticket.ticket_type("# T\n> Revision: 1\n") == "story"
    assert ticket.ticket_type("# T\n> Type: Bug\n") == "bug"
    assert ticket.ticket_type("# T\n> Type: hotfix\n") == "hotfix"
    assert ticket.ticket_type("# T\n> Type: chore\n") == "chore"


def test_ticket_type_strips_trailing_comment_and_keeps_whole_value():
    assert ticket.ticket_type("# T\n> Type: bug   # bug | hotfix\n") == "bug"
    assert ticket.ticket_type("# T\n> Type: hot fix\n") == "hot fix"
    assert ticket.ticket_type("# T\n> Type:\n") == ""


def test_ticket_type_ignores_a_type_line_in_a_comment_or_fence():
    assert ticket.ticket_type("# T\n<!-- > Type: bug -->\n") == "story"
    assert ticket.ticket_type("# T\n```\n> Type: bug\n```\n") == "story"


def test_ticket_type_reads_only_the_header_block():
    body_quote = "# T\n> Revision: 1\n\n## Summary\n> Type: individual accounts only\n"
    assert ticket.ticket_type(body_quote) == "story"
    assert ticket.ticket_type("# T\n\n## Summary\n> Type: bug\n") == "story"


def test_story_with_a_type_blockquote_in_its_body_lints_without_a_type_error():
    text = (
        "# TAL-1 — A story\n> Revision: 1\n\n## Summary\n"
        "> Type: individual accounts only\n"
    )
    assert not any("ype" in e for e in _errors(_lint(text)))


def test_header_severity_wins_over_a_severity_quote_in_the_body():
    text = _bug(
        override={"## Actual result": "> Severity: S9\nHTTP 500 on export."},
    )
    assert _errors(_lint(text)) == []


def test_body_severity_quote_does_not_stand_in_for_a_missing_header():
    text = _bug(severity=None, override={"## Actual result": "> Severity: S2\nx"})
    assert any("Severity" in e for e in _errors(_lint(text)))


def test_related_ticket_is_read_from_the_header_only():
    text = _bug(related="none", override={"## Impact": "> Related ticket: a b/c\nx"})
    assert _errors(_lint(text)) == []


# --- pass cases ---


def test_valid_bug_passes():
    report = _lint(_bug())
    assert _errors(report) == []
    assert report.render().splitlines()[-1] == "DoR: PASS"


def test_valid_hotfix_passes():
    report = _lint(_bug(type_="hotfix", severity="S1"))
    assert _errors(report) == []
    assert report.render().splitlines()[-1] == "DoR: PASS"


def test_related_ticket_with_a_safe_id_passes():
    assert _errors(_lint(_bug(related="M-billing-US3"))) == []


def test_related_ticket_absent_passes():
    assert _errors(_lint(_bug(related=None))) == []


def test_na_attachments_pass():
    text = _bug(override={"## Attachments": "N/A — server-side error, no UI."})
    assert _errors(_lint(text)) == []


# --- dispatch ---


def test_story_ticket_is_unaffected_by_dispatch():
    report = _lint("# TAL-1 — A story\n> Revision: 1\n")
    errors = _errors(report)
    assert "missing required heading: '## User Story'" in errors
    assert not any("Severity" in e for e in errors)


def test_unknown_type_is_one_error():
    report = _lint(_bug(type_="Chore"))
    assert _errors(report) == [
        "unknown ticket type 'chore' — use one of: story (no Type line), bug, hotfix"
    ]
    assert report.render().splitlines()[-1] == "DoR: FAIL"


@pytest.mark.parametrize(
    ("line", "shown"), [("> Type: hot fix", "hot fix"), ("> Type:", "")]
)
def test_malformed_type_line_is_an_unknown_type_error(line, shown):
    text = _bug().replace("> Type: bug", line)
    assert _errors(_lint(text)) == [
        f"unknown ticket type '{shown}' — use one of: story (no Type line), bug, hotfix"
    ]


def test_spec_example_header_with_trailing_comment_is_a_bug():
    text = _bug().replace("> Type: bug", "> Type: bug                 # bug | hotfix")
    assert _errors(_lint(text)) == []


# --- required structure ---


@pytest.mark.parametrize("heading", ticket.BUG_REQUIRED_HEADINGS)
def test_missing_required_heading_is_an_error(heading):
    errors = _errors(_lint(_bug(skip=(heading,))))
    assert f"missing required heading: '{heading}'" in errors


def test_empty_required_section_is_an_error():
    errors = _errors(_lint(_bug(override={"## Impact": "<who is hit>"})))
    assert any("'## Impact' is empty" in e for e in errors)


def test_missing_open_questions_is_only_a_warning():
    report = _lint(_bug(skip=("## Open questions",)))
    assert _errors(report) == []
    assert any("## Open questions" in w for w in _warnings(report))


def test_missing_title_is_an_error():
    errors = _errors(_lint(_bug(title="BUG-12 no hash")))
    assert any("level-1 title" in e for e in errors)


def test_missing_dor_checklist_rows_is_an_error():
    errors = _errors(_lint(_bug(override={"## Definition of Ready": "all good"})))
    assert any("no '- [ ]' checklist rows" in e for e in errors)


def test_unticked_dor_item_is_a_warning():
    assert any("not ticked" in w for w in _warnings(_lint(_bug())))


def test_bad_revision_flows_through_planrev():
    errors = _errors(_lint(_bug(revision="3")))
    assert any("Change log" in e or "revision" in e.lower() for e in errors)


# --- severity ---


@pytest.mark.parametrize("severity", [None, "", "S5", "high", "s1"])
def test_missing_or_invalid_severity_is_an_error(severity):
    errors = _errors(_lint(_bug(severity=severity)))
    assert any("Severity" in e for e in errors), errors


@pytest.mark.parametrize("severity", ticket.SEVERITIES)
def test_every_severity_is_accepted(severity):
    assert _errors(_lint(_bug(severity=severity))) == []


# --- links ---


def test_parent_mission_on_a_bug_is_an_error():
    errors = _errors(_lint(_bug(parent="M-billing @ rev 1")))
    assert any(
        "a bug links with `> Related ticket:`, not a parent mission" in e
        for e in errors
    )


@pytest.mark.parametrize(
    "line",
    [
        "> Parent mission: M-billing @ rev 2",
        "<!--\n> Parent mission: M-billing @ rev 2\n-->",
    ],
)
def test_parent_mission_line_anywhere_in_a_bug_is_an_error(line):
    # planrev.parent_pin reads the raw text, so lint must too.
    text = _bug(override={"## Impact": f"All exports.\n{line}"})
    errors = _errors(_lint(text))
    assert any("not a parent mission" in e for e in errors), errors


@pytest.mark.parametrize("related", ["../etc", "a b/c", "-x", "", "x/y"])
def test_related_ticket_must_be_none_or_a_safe_id(related):
    errors = _errors(_lint(_bug(related=related)))
    assert any("Related ticket" in e for e in errors), errors


# --- steps ---


def test_steps_without_a_numbered_item_is_an_error():
    text = _bug(override={"## Steps to reproduce": "Open Billing then click Export."})
    assert any("numbered" in e for e in _errors(_lint(text)))


def test_bulleted_steps_are_not_numbered():
    text = _bug(override={"## Steps to reproduce": "- Open Billing\n- Click Export"})
    assert any("numbered" in e for e in _errors(_lint(text)))


# --- placeholders from the template's literal lines ---


def test_template_placeholder_steps_are_an_error():
    text = _bug(override={"## Steps to reproduce": "1. <step>\n2. <step>"})
    assert any("Steps to reproduce" in e for e in _errors(_lint(text)))


def test_one_real_step_among_placeholders_passes():
    text = _bug(override={"## Steps to reproduce": "1. Open Billing.\n2. <step>"})
    assert _errors(_lint(text)) == []


def test_placeholder_na_reason_is_an_error():
    text = _bug(override={"## Attachments": "N/A — <reason>"})
    assert any("Attachments" in e for e in _errors(_lint(text)))


def test_placeholder_image_src_is_an_error_without_a_path():
    text = _bug(override={"## Attachments": "![<caption>](BUG-<n>/<file>.png)"})
    assert any("placeholder" in e for e in _errors(_lint(text)))


# --- attachments ---


def test_attachments_without_image_or_na_is_an_error():
    text = _bug(override={"## Attachments": "see the screenshot I sent"})
    assert any("Attachments" in e for e in _errors(_lint(text)))


def test_na_without_a_reason_is_an_error():
    text = _bug(override={"## Attachments": "N/A"})
    assert any("Attachments" in e for e in _errors(_lint(text)))


@pytest.mark.parametrize(
    ("src", "fragment"),
    [
        ("https://x.example/a.png", "external"),
        ("//x.example/a.png", "external"),
        ("/abs/BUG-12/a.png", "absolute"),
        ("C:/tmp/a.png", "absolute"),
        ("BUG-12/../BUG-13/a.png", ".."),
        ("other/a.png", "BUG-12/"),
        ("a.png", "BUG-12/"),
        ("BUG-12/shot.jpg", "PNG"),
        ("BUG-12/shot.gif", "PNG"),
        ("BUG-12/noext", "PNG"),
    ],
)
def test_bad_image_src_is_an_error(src, fragment):
    text = _bug(override={"## Attachments": f"![shot]({src})"})
    errors = _errors(_lint(text, ticket_id="BUG-12"))
    assert any(fragment in e for e in errors), errors


def test_png_and_webp_are_accepted_any_case():
    text = _bug(override={"## Attachments": "![a](BUG-12/a.PNG)\n![b](BUG-12/b.webp)"})
    assert _errors(_lint(text, ticket_id="BUG-12")) == []


def test_folder_check_uses_path_stem(tmp_path):
    path = _bug_file(tmp_path, _bug(override={"## Attachments": "![x](BUG-99/x.png)"}))
    assert any("BUG-12/" in e for e in _errors(_lint(path.read_text(), path=path)))


def test_folder_check_skipped_when_stem_unknown():
    text = _bug(override={"## Attachments": "![x](anything/x.png)"})
    assert _errors(_lint(text)) == []


def test_missing_file_on_disk_is_an_error_when_path_known(tmp_path):
    text = _bug()
    path = _bug_file(tmp_path, text, image=False)
    assert any("not found" in e for e in _errors(_lint(text, path=path)))


def test_existing_file_on_disk_passes(tmp_path):
    text = _bug()
    path = _bug_file(tmp_path, text)
    assert _errors(_lint(text, path=path)) == []


def test_mcp_style_call_checks_shape_only():
    # No path: the image is not on disk and that is fine.
    assert _errors(_lint(_bug())) == []


def test_images_in_comments_or_fences_do_not_count():
    text = _bug(
        override={
            "## Attachments": "<!-- ![x](BUG-12/x.png) -->\n```\n![y](BUG-12/y.png)\n```"
        }
    )
    assert any("Attachments" in e for e in _errors(_lint(text)))


# --- public helpers (Task 2 reuses them) ---


def test_attachment_images_lists_raw_srcs():
    text = _bug(override={"## Attachments": "![a](BUG-12/a.png)\n![b](BUG-12/b.png)"})
    assert buglint.attachment_images(text) == ["BUG-12/a.png", "BUG-12/b.png"]
    assert buglint.attachment_images("# T\n") == []


def test_image_problems_clean_src(tmp_path):
    (tmp_path / "BUG-12").mkdir()
    (tmp_path / "BUG-12" / "a.png").write_bytes(_PNG)
    assert buglint.image_problems("BUG-12/a.png", "BUG-12", tmp_path) == []
    assert buglint.image_problems("BUG-12/b.png", "BUG-12", tmp_path) != []
    assert buglint.image_problems("BUG-12/b.png", "BUG-12", None) == []


# --- KB context is validated only when present ---


def test_kb_context_block_is_checked_when_present():
    text = _bug(
        override={},
        extra="\n## KB context\n```yaml\nnot: a context\n```\n",
    )
    errors = _errors(_lint(text))
    assert errors, "a present-but-malformed KB context must be reported"


def test_hotfix_is_not_tied_to_a_severity():
    assert _errors(_lint(_bug(type_="hotfix", severity="S4"))) == []


# --- template ---


_TEMPLATE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "strata_kb"
    / "templates"
    / "init"
    / "bug-template.md"
)


def test_template_has_every_bug_heading_once():
    content = _TEMPLATE.read_text(encoding="utf-8")
    for heading in (*ticket.BUG_REQUIRED_HEADINGS, *ticket.BUG_RECOMMENDED_HEADINGS):
        assert content.count(f"\n{heading}\n") == 1, heading


def test_unfilled_template_fails_lint_on_placeholders():
    report = _lint(_TEMPLATE.read_text(encoding="utf-8"))
    errors = _errors(report)
    assert not report.passed
    assert any("Steps to reproduce" in e for e in errors)
    assert (
        "image 'BUG-<n>/<file>.png' is still a template placeholder — fill it in"
        in errors
    )


def test_filled_template_passes():
    content = _TEMPLATE.read_text(encoding="utf-8")
    filled = content.replace("> Type: bug", "> Type: bug", 1)
    for heading, body in _SECTIONS.items():
        head, _, rest = filled.partition(f"\n{heading}\n")
        tail = rest.split("\n## ", 1)
        after = "\n## " + tail[1] if len(tail) > 1 else "\n"
        filled = head + f"\n{heading}\n{body}\n" + after
    import re

    filled = re.sub(
        r"^# .*$", "# BUG-12 — Export returns 500", filled, count=1, flags=re.M
    )
    filled = re.sub(r"^> Severity:.*$", "> Severity: S2", filled, count=1, flags=re.M)
    filled = re.sub(
        r"^> Related ticket:.*$", "> Related ticket: none", filled, count=1, flags=re.M
    )
    report = _lint(filled, ticket_id="BUG-12")
    assert _errors(report) == [], filled
    assert report.render().splitlines()[-1] == "DoR: PASS"
