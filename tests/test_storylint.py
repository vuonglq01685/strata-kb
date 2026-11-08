from __future__ import annotations

import pytest

from strata_kb import storylint, ticket

PID = "M-x-US1"
API = f"{PID}.api"
WEB = f"{PID}.web"

STORY = "As a user, I want to export, so that I can share."


def parent(rows: str | None = None, extra: str = "", kind: str = "parent story") -> str:
    rows = (
        rows
        if rows is not None
        else f"| {API} | api | AC1, AC2 | - | - | data |\n"
        f"| {WEB} | web | AC3, AC4 | {API} | - | ui |\n"
    )
    return (
        f"# Export {PID}\n> Kind: {kind}\n> Revision: 1\n\n"
        f"## User Story\n{STORY}\n\n"
        "## Split\n| Child | Repo | AC | Blocked by | Own fix | Why |\n"
        f"|---|---|---|---|---|---|\n{rows}\n"
        "## Change log\n| Rev | Date | Trigger | What changed | Affected | Review |\n"
        "|---|---|---|---|---|---|\n" + extra
    )


def child(
    cid: str, repo: str, acs: list[str], blocked: str = "None", story: str = STORY
):
    items = "\n".join(f"- [ ] {a} — Given x, when y, then z" for a in acs)
    return (
        f"# {cid}\n> Revision: 1\n> Parent story: {PID} @ rev 1\n> Target repo: {repo}\n\n"
        f"## User Story\n{story}\n\n## Acceptance Criteria\n{items}\n\n"
        f"## Dependencies\n- Blocked by: {blocked}\n"
    )


def kids():
    return {
        API: child(API, "api", ["AC1", "AC2"]),
        WEB: child(WEB, "web", ["AC3", "AC4"], blocked=f"{API} — needs data"),
    }


def errors(report) -> str:
    return "\n".join(i.message for i in report.issues if i.level == "error")


def test_passing_fixture():
    r = storylint.lint_parent(parent(), kids(), parent_id=PID)
    assert r.passed, errors(r)
    p = parent()
    for cid, text in kids().items():
        assert storylint.lint_child_against_parent(text, cid, p, PID) == []


def test_parse_split_reads_dotted_ids():
    rows = storylint.parse_split(parent())
    assert [r.child for r in rows] == [API, WEB]
    assert rows[1].blocked_by == (API,)
    assert rows[0].acs == ("AC1", "AC2")


def test_child_id_re():
    m = ticket.CHILD_ID_RE.match("M-x-US1.api.2")
    assert m and m.group("parent") == "M-x-US1" and m.group("repo") == "api"
    assert ticket.CHILD_ID_RE.match("M-x-US1.api")
    for bad in ("M-x-US1", "M-x-US1.api.1", "M-x-US1.api.2.3", "M-x-US1.", ".api"):
        assert ticket.CHILD_ID_RE.match(bad) is None, bad


def test_ac_in_two_children_is_error():
    rows = (
        f"| {API} | api | AC1, AC2 | - | - | d |\n| {WEB} | web | AC2 | - | - | u |\n"
    )
    assert "AC2" in errors(storylint.lint_parent(parent(rows), kids(), parent_id=PID))


def test_replaces_lets_old_ac_stay_in_done_child():
    rows = f"| {API} | api | AC1, AC2 | - | - | d |\n| {WEB} | web | AC7 (replaces AC2) | - | - | u |\n"
    p = parent(rows)
    assert storylint.parse_split(p)[1].replaces == {"AC7": "AC2"}
    c = {**kids(), WEB: child(WEB, "web", ["AC7"])}
    assert storylint.lint_parent(p, c, parent_id=PID).passed


def test_split_child_missing_file_is_error():
    c = {**kids(), WEB: None}
    assert WEB in errors(storylint.lint_parent(parent(), c, parent_id=PID))


def test_cycle_in_split_is_error():
    rows = f"| {API} | api | AC1 | {WEB} | - | d |\n| {WEB} | web | AC3 | {API} | - | u |\n"
    out = errors(storylint.lint_parent(parent(rows), kids(), parent_id=PID))
    assert f"dependency cycle: {API} → {WEB} → {API}" in out


def test_blocked_by_unknown_child_is_error():
    rows = f"| {API} | api | AC1 | {PID}.ghost | - | d |\n"
    assert "ghost" in errors(storylint.lint_parent(parent(rows), kids(), parent_id=PID))


def test_duplicate_and_wrong_parent_child_ids_are_errors():
    rows = f"| {API} | api | AC1 | - | - | d |\n| {API} | api | AC2 | - | - | d |\n| Other.web | web | AC3 | - | - | d |\n"
    out = errors(storylint.lint_parent(parent(rows), kids(), parent_id=PID))
    assert "listed twice" in out and "Other.web" in out


def test_parent_with_dor_is_error():
    p = parent() + "\n## Definition of Ready\n- [ ] x\n"
    assert "Definition of Ready" in errors(
        storylint.lint_parent(p, kids(), parent_id=PID)
    )


def test_parent_with_acceptance_criteria_is_error():
    p = parent() + "\n## Acceptance Criteria\n- [ ] AC1 — x\n"
    assert "Acceptance Criteria" in errors(
        storylint.lint_parent(p, kids(), parent_id=PID)
    )


def test_missing_kind_revision_and_headings_are_errors():
    out = errors(storylint.lint_parent("# T\n\n## Split\n", {}, parent_id=PID))
    assert "Kind" in out and "Revision" in out and "## User Story" in out


def test_split_wrong_columns_is_error():
    p = parent().replace("| Own fix |", "| Fix |")
    assert "columns must be exactly" in errors(
        storylint.lint_parent(p, kids(), parent_id=PID)
    )


def test_revision_without_change_log_row_is_error():
    p = parent().replace("> Revision: 1", "> Revision: 2")
    assert "Revision 2" in errors(storylint.lint_parent(p, kids(), parent_id=PID))


def test_child_parent_missing_is_error():
    issues = storylint.lint_child_against_parent(kids()[API], API, None, PID)
    assert [i.message for i in issues] == [
        f"parent story {PID} not found — pass its text or keep it in the same folder"
    ]


def test_child_without_parent_story_header_is_error():
    text = kids()[API].replace(f"> Parent story: {PID} @ rev 1\n", "")
    out = storylint.lint_child_against_parent(text, API, parent(), PID)
    assert any("Parent story" in i.message for i in out)


def test_child_not_in_split_is_error():
    out = storylint.lint_child_against_parent(kids()[API], f"{PID}.zzz", parent(), PID)
    assert any("not listed" in i.message for i in out)


def test_child_ac_ids_differ_from_split_is_error():
    text = child(API, "api", ["AC1", "AC9"])
    out = storylint.lint_child_against_parent(text, API, parent(), PID)
    assert any("AC ids" in i.message for i in out)


def test_child_needs_two_acs():
    out = storylint.lint_child_against_parent(
        child(API, "api", ["AC1"]), API, parent(), PID
    )
    assert any("at least 2" in i.message for i in out)


def test_child_blocked_by_differs_from_split_is_error():
    text = child(WEB, "web", ["AC3", "AC4"], blocked="None")
    out = storylint.lint_child_against_parent(text, WEB, parent(), PID)
    assert any("Blocked by" in i.message for i in out)


def test_child_target_repo_differs_is_error():
    text = child(API, "web", ["AC1", "AC2"])
    out = storylint.lint_child_against_parent(text, API, parent(), PID)
    assert any("Target repo" in i.message for i in out)


def test_child_user_story_differs_is_error():
    text = child(API, "api", ["AC1", "AC2"], story="As a bot, I want x, so that y.")
    out = storylint.lint_child_against_parent(text, API, parent(), PID)
    assert any("User Story" in i.message for i in out)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("# T\n> Kind: Parent Story  # note\n\n## A\n", "parent story"),
        ("# T\n\n## A\n> Kind: parent story\n", None),
    ],
)
def test_ticket_kind(text, expected):
    assert ticket.ticket_kind(text) == expected


def test_parent_story_pin():
    assert ticket.parent_story_pin("# T\n> Parent story: P @ rev 3\n") == ("P", 3)
    assert ticket.parent_story_pin("# T\n> Parent story: P\n") == ("P", 1)
    assert ticket.parent_story_pin("# T\n") is None


def test_child_blocked_by_prose_with_dotted_words_is_ignored():
    p = parent()
    for prose in ("None — see README.md", "None (waiting for v1.2 release)"):
        text = child(API, "api", ["AC1", "AC2"], blocked=prose)
        assert storylint.lint_child_against_parent(text, API, p, PID) == [], prose


def test_short_split_row_is_error():
    rows = f"| {API} | api | AC1, AC2 | - | - | d |\n| {WEB} | web | AC3 |\n"
    out = errors(storylint.lint_parent(parent(rows), kids(), parent_id=PID))
    assert "split row 2 has 3 cells, expected 6" in out


def test_dotted_repo_id_cannot_be_split_target():
    cid = f"{PID}.my.app"
    rows = f"| {cid} | my.app | AC1 | - | - | d |\n"
    out = errors(storylint.lint_parent(parent(rows), {cid: "x"}, parent_id=PID))
    assert "repo ids containing '.' cannot be split targets" in out


# --- final review: the parent lint checks every written child ---


def moved_ac_parent() -> str:
    return parent(
        f"| {API} | api | AC1, AC2, AC3 | - | - | data |\n"
        f"| {WEB} | web | AC4 | {API} | - | ui |\n"
    )


def test_parent_lint_catches_ac_moved_in_split_with_children_unchanged():
    out = errors(storylint.lint_parent(moved_ac_parent(), kids(), parent_id=PID))
    assert f"child '{API}' AC ids" in out and f"child '{WEB}' AC ids" in out


def test_parent_lint_does_not_ask_children_for_two_acs():
    p = parent(
        f"| {API} | api | AC1, AC2 | - | - | data |\n"
        f"| {WEB} | web | AC3 | {API} | - | ui |\n"
    )
    c = {API: child(API, "api", ["AC1", "AC2"]), WEB: child(WEB, "web", ["AC3"], API)}
    assert storylint.lint_parent(p, c, parent_id=PID).passed


@pytest.mark.parametrize(
    ("edit", "needle"),
    [
        (lambda t: t.replace(f"> Parent story: {PID} @ rev 1\n", ""), "needs"),
        (lambda t: t.replace(f"{PID} @ rev 1", "M-x-US9 @ rev 1"), "needs"),
        (
            lambda t: t.replace("> Target repo: web", "> Target repo: api"),
            "Target repo",
        ),
        (lambda t: t.replace(f"{API} — needs data", "None"), "Blocked by"),
        (lambda t: t.replace(STORY, "Another story."), "User Story"),
    ],
)
def test_parent_lint_checks_each_written_child_against_its_row(edit, needle):
    c = kids()
    c[WEB] = edit(c[WEB])
    assert needle in errors(storylint.lint_parent(parent(), c, parent_id=PID))


def test_parent_lint_skips_a_demoted_child():
    log = f"| 2 | 2026-10-11 | scope | AC moved | {WEB} | B4 D4 (agent) |\n"
    p = parent(
        f"| {API} | api | AC1, AC2, AC3 | - | - | data |\n"
        f"| {WEB} | web | AC4 | {API} | - | ui |\n",
        extra=log,
    ).replace("> Revision: 1", "> Revision: 2")
    out = errors(storylint.lint_parent(p, kids(), parent_id=PID))
    assert f"child '{API}' AC ids" in out  # not listed in the later row
    assert f"child '{WEB}'" not in out  # pinned rev 1 < 2 and listed: demoted


@pytest.mark.parametrize(
    "line",
    [
        "> Parent story: P-1 @ rev 3",
        "> Parent story: P-1 @rev 3",
        "> Parent story: P-1 @ rev3",
        "> Parent story: P-1 @rev3",
        "> Parent story: P-1 @ rev 3\r",
    ],
)
def test_parent_story_pin_accepts_spacing_and_crlf(line: str):
    assert ticket.parent_story_pin(f"# T\n{line}\n\n## X\n") == ("P-1", 3)


def warnings(report) -> list[str]:
    return [i.message for i in report.issues if i.level == "warning"]


def planned_rows(web_ac: str = "-") -> str:
    return (
        f"| {API} | api | AC1, AC2 | - | - | data |\n"
        f"| {WEB} | web | {web_ac} | - | - | ui |\n"
    )


def test_planned_unwritten_child_lints():
    r = storylint.lint_parent(
        parent(planned_rows()), {API: kids()[API], WEB: None}, parent_id=PID
    )
    assert not errors(r), errors(r)
    assert [
        storylint.is_planned(x) for x in storylint.parse_split(parent(planned_rows()))
    ] == [False, True]


def test_deleted_child_with_acs_still_errors():
    r = storylint.lint_parent(
        parent(planned_rows("AC3, AC4")), {API: kids()[API], WEB: None}, parent_id=PID
    )
    assert f"split child '{WEB}' has no ticket file" in errors(r)


def test_written_child_on_planned_row_errors():
    r = storylint.lint_parent(parent(planned_rows()), kids(), parent_id=PID)
    assert errors(r)  # existing AC-mismatch rule: file owns AC3, AC4, row says "-"


def test_filled_planned_row_reuses_sibling_ac_errors():
    r = storylint.lint_parent(
        parent(planned_rows("AC2, AC3")), {API: kids()[API], WEB: None}, parent_id=PID
    )
    assert "AC2 is in more than one split child" in errors(r)


def test_missing_split_decision_is_a_warning():
    r = storylint.lint_parent(parent(), kids(), parent_id=PID)
    assert warnings(r) == [
        "no '**Split decision:**' line under '## Change log' — record who accepted the split"
    ]


def test_split_decision_line_silences_the_warning():
    line = f"\n**Split decision:** 2026-11-06 — 2 children: {API}, {WEB} — evidence: x — accepted by: BA\n"
    r = storylint.lint_parent(parent(extra=line), kids(), parent_id=PID)
    assert warnings(r) == []


def test_shipped_parent_template_warns_until_a_split_decision_is_written():
    from strata_kb.initcmd import read_template

    text = read_template("parent-story-template.md").replace(
        "<parent-id>.<repo-id>", API
    )
    r = storylint.lint_parent(text, {API: kids()[API]}, parent_id=PID)
    assert (
        "no '**Split decision:**' line under '## Change log' — record who accepted the split"
        in warnings(r)
    )


def _logged(affected: str) -> str:
    return parent(
        extra=f"| 2 | 2026-11-07 | scope | change | {affected} | B4 (agent) |\n"
    ).replace("> Revision: 1", "> Revision: 2")


def test_change_log_affected_must_be_split_children():
    r = storylint.lint_parent(_logged(f"{API}, {PID}.mobile"), kids(), parent_id=PID)
    assert (
        f"change-log row 2: Affected '{PID}.mobile' is not a child in the split"
        in errors(r)
    )
    assert "Affected 'M-x-US1.api'" not in errors(r)


@pytest.mark.parametrize("cell", ["-", "", f"{API}, {WEB}"])
def test_change_log_affected_dash_allowed(cell):
    r = storylint.lint_parent(_logged(cell), kids(), parent_id=PID)
    assert "Affected" not in errors(r), errors(r)


def _two_rows(old: str, new: str) -> str:
    return parent(
        extra=f"| 2 | 2026-11-06 | scope | a | {old} | B4 (agent) |\n"
        f"| 3 | 2026-11-07 | scope | b | {new} | B4 (agent) |\n"
    ).replace("> Revision: 1", "> Revision: 3")


def test_change_log_older_row_naming_a_gone_child_is_a_warning():
    gone = f"{PID}.mobile"
    r = storylint.lint_parent(_two_rows(f"{API}, {gone}", API), kids(), parent_id=PID)
    msg = f"change-log row 2: Affected '{gone}' is not a child in the split"
    assert msg not in errors(r)
    assert msg in "\n".join(i.message for i in r.issues if i.level == "warning")


def test_change_log_newest_row_naming_a_gone_child_is_an_error():
    gone = f"{PID}.mobile"
    r = storylint.lint_parent(_two_rows(API, f"{API}, {gone}"), kids(), parent_id=PID)
    assert f"change-log row 3: Affected '{gone}' is not a child in the split" in errors(
        r
    )


# --- parent bug: an own-fix row plus child bugs, no ACs ---

BID = "BUG-7"
BAPI = f"{BID}.api"
BWEB = f"{BID}.web"
OWN = f"| {BID} | api | - | - | yes | first responder fixes it |\n"
BROWS = (
    OWN
    + f"| {BAPI} | api | - | - | - | data |\n"
    + f"| {BWEB} | web | - | {BAPI} | - | ui |\n"
)


def parent_bug(rows: str = BROWS) -> str:
    text = parent(rows=rows, kind="parent bug").replace(PID, BID)
    return text.replace(f"## User Story\n{STORY}\n\n", "")


def child_bug(cid: str, repo: str, blocked: str = "None", pin: str = BID) -> str:
    return (
        f"# {cid} — x\n> Type: bug\n> Revision: 1\n> Parent bug: {pin} @ rev 1\n"
        f"> Target repo: {repo}\n\n## Summary\nx\n\n"
        f"## Dependencies\n- Blocked by: {blocked}\n"
    )


def bug_kids() -> dict[str, str | None]:
    return {
        BAPI: child_bug(BAPI, "api"),
        BWEB: child_bug(BWEB, "web", blocked=BAPI),
    }


def test_parent_bug_lints():
    r = storylint.lint_parent(parent_bug(), bug_kids(), parent_id=BID)
    assert r.passed, errors(r)
    own = storylint.own_row(storylint.parse_split(parent_bug()), BID)
    assert own is not None and own.own_fix == "yes"
    for cid, text in bug_kids().items():
        assert (
            storylint.lint_bug_child_against_parent(text, cid, parent_bug(), BID) == []
        )


def test_parent_bug_needs_exactly_one_own_row():
    rows = BROWS.removeprefix(OWN)
    out = errors(storylint.lint_parent(parent_bug(rows), bug_kids(), parent_id=BID))
    assert (
        f"parent bug needs exactly one split row for {BID} itself (its own fix)" in out
    )


def test_parent_bug_duplicate_own_row():
    out = errors(
        storylint.lint_parent(parent_bug(OWN + BROWS), bug_kids(), parent_id=BID)
    )
    assert "exactly one split row" in out


def test_parent_bug_own_fix_value():
    rows = BROWS.replace("| yes |", "| maybe |")
    out = errors(storylint.lint_parent(parent_bug(rows), bug_kids(), parent_id=BID))
    assert f"split row {BID}: Own fix must be yes or no" in out
    ok = BROWS.replace("| yes |", "| no |")
    assert storylint.lint_parent(parent_bug(ok), bug_kids(), parent_id=BID).passed


def test_parent_bug_child_rows_need_own_fix_dash():
    rows = BROWS.replace(
        f"| {BAPI} | api | - | - | - |", f"| {BAPI} | api | - | - | yes |"
    )
    out = errors(storylint.lint_parent(parent_bug(rows), bug_kids(), parent_id=BID))
    assert f"split child '{BAPI}': Own fix must be -" in out


def test_parent_bug_split_has_no_acs():
    rows = BROWS.replace(f"| {BAPI} | api | - |", f"| {BAPI} | api | AC1 |")
    out = errors(storylint.lint_parent(parent_bug(rows), bug_kids(), parent_id=BID))
    assert "a parent bug's split has no ACs" in out


def test_parent_bug_child_rules_and_missing_file():
    bad_id = BROWS.replace(BWEB, "BUG-9.web")
    out = errors(storylint.lint_parent(parent_bug(bad_id), bug_kids(), parent_id=BID))
    assert "not 'BUG-7.<repo>'" in out
    gone = {**bug_kids(), BWEB: None}
    out = errors(storylint.lint_parent(parent_bug(), gone, parent_id=BID))
    assert f"split child '{BWEB}' has no ticket file" in out
    assert BID not in out.replace("BUG-7.", "").replace("BUG-7 itself", "")
    cyc = BROWS.replace(f"| {BAPI} | api | - | - |", f"| {BAPI} | api | - | {BWEB} |")
    assert "dependency cycle" in errors(
        storylint.lint_parent(parent_bug(cyc), bug_kids(), parent_id=BID)
    )


def test_child_bug_pin_and_target_must_match():
    p = parent_bug()
    wrong_pin = child_bug(BAPI, "api", pin="BUG-8")
    out = storylint.lint_bug_child_against_parent(wrong_pin, BAPI, p, BID)
    assert any("> Parent bug: BUG-7" in i.message for i in out)
    wrong_target = child_bug(BAPI, "web")
    out = storylint.lint_bug_child_against_parent(wrong_target, BAPI, p, BID)
    assert any("'> Target repo:' differs" in i.message for i in out)
    wrong_block = child_bug(BWEB, "web", blocked="None")
    out = storylint.lint_bug_child_against_parent(wrong_block, BWEB, p, BID)
    assert any("Blocked by" in i.message for i in out)
    assert any(
        "not found" in i.message
        for i in storylint.lint_bug_child_against_parent(wrong_pin, BAPI, None, BID)
    )


def test_parent_bug_pin_is_parsed():
    text = "# BUG-7.api\n> Type: bug\n> Parent bug: BUG-7 @ rev 2\n"
    assert ticket.parent_story_pin(text) == ("BUG-7", 2)


def test_planparents_covers_parent_bug():
    from strata_kb import planparents

    assert planparents.is_parent(parent_bug()) and planparents.is_parent_bug(
        parent_bug()
    )
    assert planparents.is_parent(parent()) and not planparents.is_parent_bug(parent())


def test_parent_bug_own_row_blocked_by_children_lints():
    own = f"| {BID} | api | - | {BAPI}, {BWEB} | yes | waits for both |\n"
    rows = own + BROWS.removeprefix(OWN)
    r = storylint.lint_parent(parent_bug(rows), bug_kids(), parent_id=BID)
    assert r.passed, errors(r)
