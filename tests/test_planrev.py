"""planrev — mission/ticket revision, change log, parent-mission pin."""

from __future__ import annotations

from strata_kb import planrev, ticket

_HEADER = "| Rev | Date | Trigger | What changed | Affected | Review |\n|---|---|---|---|---|---|\n"


def _doc(revision: int | None, *rows: str) -> str:
    out = "# Title\n"
    if revision is not None:
        out += f"> Revision: {revision}\n"
    if rows:
        out += f"\n## Change log\n{_HEADER}" + "".join(r + "\n" for r in rows)
    return out


def _row(rev: int, trigger: str = "scope") -> str:
    return f"| {rev} | 2026-10-11 | {trigger} | changed | - | B4 D4 (agent) |"


def test_parse_revision_absent_is_none():
    assert planrev.parse_revision("# T\n\nbody\n") is None


def test_parse_revision_reads_integer():
    assert planrev.parse_revision("# T\n> Revision: 3\n") == 3


def test_parse_change_log_rows():
    text = _doc(
        2,
        "| 2 | 2026-10-11 | architecture, scope | split US3 | M-x-US3, M-x-US7 | B4 D4 (agent) |",
    )
    assert planrev.parse_change_log(text) == [
        planrev.ChangeRow(
            2,
            "2026-10-11",
            ("architecture", "scope"),
            "split US3",
            ("M-x-US3", "M-x-US7"),
            "B4 D4 (agent)",
        )
    ]


def test_parse_change_log_dash_affected_is_empty():
    assert planrev.parse_change_log(_doc(2, _row(2)))[0].affected == ()


def test_check_revision_absent_warns_only():
    issues = planrev.check_revision(_doc(None))
    assert [i.level for i in issues] == ["warning"]


def test_check_revision_requires_row_per_revision():
    issues = planrev.check_revision(_doc(3, _row(2)))
    assert [i.level for i in issues] == ["error"]
    assert "3" in issues[0].message


def test_check_revision_rows_out_of_order_error():
    issues = planrev.check_revision(_doc(3, _row(3), _row(2)))
    assert [i.level for i in issues] == ["error"]


def test_check_revision_unknown_trigger_error():
    issues = planrev.check_revision(_doc(2, _row(2, "rewrite")))
    assert [i.level for i in issues] == ["error"]
    assert "rewrite" in issues[0].message


def test_check_revision_complete_log_passes():
    assert (
        planrev.check_revision(_doc(3, _row(2), _row(3, "kb-context, delivery"))) == []
    )


def test_check_revision_rev1_no_log_passes():
    assert planrev.check_revision(_doc(1)) == []


def test_parent_pin_default_rev1():
    assert planrev.parent_pin("> Parent mission: M-demo\n") == ("M-demo", 1)


def test_parent_pin_with_rev():
    assert planrev.parent_pin("> Parent mission: M-demo @ rev 4\n") == ("M-demo", 4)


def test_parent_pin_absent_is_none():
    assert planrev.parent_pin("# T\n") is None


def test_parent_mission_re_accepts_rev_suffix():
    for line in ("> Parent mission: M-demo", "> Parent mission: M-demo @ rev 4"):
        m = ticket.PARENT_MISSION_RE.search(line)
        assert m is not None and m.group(1) == "M-demo"


def test_shipped_templates_carry_revision_and_clean_change_log():
    from importlib.resources import files

    for name in ("mission-template.md", "ticket-template.md"):
        text = (files("strata_kb") / "templates" / "init" / name).read_text(
            encoding="utf-8"
        )
        assert planrev.parse_revision(text) == 1
        assert text.index(planrev.CHANGE_LOG_HEADING) < text.index("## Review record")
        assert planrev.check_revision(text) == []
