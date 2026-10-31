import subprocess

from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.l3check import fixrecord, report
from strata_kb.l3check.fixrecord import BaselineUnit, FixEntry, L3Fix
from strata_kb.l3check.report import AgentVerdict, Finding, L3Check, SectionCheck
from tests.test_l3check_report import _flag, _kb

runner = CliRunner()


def _git_kb(tmp_path):
    # `kb l3 confirm` resolves the reviewer from the enclosing git repo
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return _kb(tmp_path)


def _invoke(kb, *args):
    return runner.invoke(app, ["l3", *args, "--kb-dir", str(kb)])


def test_report_lists_findings_and_exits_1(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    finding = Finding(
        kind="order",
        page=3,
        evidence={"other": "z", "pdf": "p text", "l3": "l text"},
        agent=AgentVerdict(verdict="unsure", reason="cannot tell"),
    )
    report.save(
        kb / "doc",
        L3Check(
            checked_at="t",
            sections=[
                SectionCheck(id="1", l3_sha256=digests["1"], findings=[finding]),
                SectionCheck(
                    id="2",
                    l3_sha256=digests["2"],
                    findings=[Finding(kind="content")],
                ),
            ],
        ),
    )

    result = _invoke(kb, "report")

    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert "§1" in lines
    assert "  [order] p.3 l3: l text | pdf: p text | other: z" in lines
    assert "    agent: unsure — cannot tell" in lines
    assert "  [content] p.?" in lines
    assert "2 section(s) awaiting review." in result.output


def test_report_clean_exits_0(tmp_path):
    kb = _git_kb(tmp_path)

    result = _invoke(kb, "report", "doc")

    assert result.exit_code == 0
    assert "L3 check: nothing awaiting review." in result.output


def test_confirm_section_then_report_clean(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1")

    result = _invoke(kb, "confirm", "doc", "--section", "1", "--by", "Rev <r@x>")

    assert result.exit_code == 0
    assert "confirmed: §1" in result.output
    assert _invoke(kb, "report").exit_code == 0


def test_confirm_all_requires_yes_or_prompt(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1", "2")

    declined = runner.invoke(
        app,
        ["l3", "confirm", "doc", "--all", "--by", "r", "--kb-dir", str(kb)],
        input="n\n",
    )
    assert declined.exit_code == 1
    assert "Confirm all 2 flagged section(s) of doc?" in declined.output
    assert report.blocked_docs(kb) == [("doc", ["1", "2"])]

    accepted = _invoke(kb, "confirm", "doc", "--all", "--by", "r", "--yes")
    assert accepted.exit_code == 0
    assert "confirmed: §1, §2" in accepted.output
    assert report.blocked_docs(kb) == []


def test_confirm_requires_section_or_all(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1")

    neither = _invoke(kb, "confirm", "doc", "--by", "r")
    both = _invoke(
        kb, "confirm", "doc", "--section", "1", "--all", "--yes", "--by", "r"
    )

    assert neither.exit_code == 2
    assert both.exit_code == 2
    assert report.blocked_docs(kb) == [("doc", ["1"])]


def test_confirm_unknown_section_exit_1(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1")

    result = _invoke(kb, "confirm", "doc", "--section", "9", "--by", "r")

    assert result.exit_code == 1
    assert "no flagged section 9" in result.output


def test_status_shows_l3_line(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1", "2")

    result = runner.invoke(app, ["status", "--kb-dir", str(kb)])

    assert result.exit_code == 0
    assert "  L3 check: 2 section(s) awaiting review" in result.output


def test_corrupt_l3check_is_one_clean_line(tmp_path):
    kb = _git_kb(tmp_path)
    (kb / "doc" / report.FILE_NAME).write_text("sections: [oops", encoding="utf-8")
    cases = (
        ["status"],
        ["l3", "report"],
        ["l3", "confirm", "doc", "--all", "--yes", "--by", "r"],
    )

    for args in cases:
        result = runner.invoke(app, [*args, "--kb-dir", str(kb)])

        assert result.exit_code == 1, args
        assert f"{report.FILE_NAME} is invalid" in result.output, args
        assert "Traceback" not in result.output, args


def test_confirm_with_corrupt_manifest_is_one_clean_line(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1")
    (kb / "doc" / "_manifest.yaml").write_text("sections: [oops", encoding="utf-8")

    result = runner.invoke(
        app,
        ["l3", "confirm", "doc", "--all", "--yes", "--by", "r", "--kb-dir", str(kb)],
    )

    assert result.exit_code == 1
    assert "_manifest.yaml is invalid" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_report_empty_kb_exits_0(tmp_path):
    result = _invoke(tmp_path / ".kb", "report")

    assert result.exit_code == 0
    assert "KB is empty — no index.yaml yet." in result.output


def test_confirm_all_without_l3check_file_fails_before_prompting(tmp_path):
    kb = _git_kb(tmp_path)

    result = runner.invoke(
        app, ["l3", "confirm", "doc", "--all", "--by", "r", "--kb-dir", str(kb)]
    )

    assert result.exit_code == 1
    assert f"no {report.FILE_NAME} for doc" in result.output
    assert "Confirm all" not in result.output


def test_confirm_section_gone_from_l3_exit_1(tmp_path):
    kb = _git_kb(tmp_path)
    _flag(kb, "1")
    (kb / "doc" / "a.raw.md").unlink()

    result = _invoke(kb, "confirm", "doc", "--section", "1", "--by", "r")

    assert result.exit_code == 1
    assert "section not found in L3" in result.output


def _fix(kb, *, baseline=None, entries=None):
    fixrecord.save(
        kb / "doc",
        L3Fix(
            baseline={
                k: BaselineUnit(file="a", l3_sha256=h)
                for k, h in (baseline or {}).items()
            },
            sections=entries or [],
        ),
    )


def _fix_entry(sid, sha, **kw):
    kw = {"by": "cursor", "at": "t", **kw}
    return FixEntry(id=sid, file="a", l3_sha256=sha, **kw)


def test_report_lists_ai_fix_first_with_diff_hint(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _flag(kb, "1")
    _fix(
        kb,
        baseline={"2": digests["2"], "x1": "gone"},
        entries=[
            _fix_entry(
                "1",
                digests["1"],
                by="claude-code",
                verified=False,
                changes=["text"],
            )
        ],
    )
    raw = kb / "doc" / "a.raw.md"
    raw.write_text(raw.read_text(encoding="utf-8").replace("beta", "BETA"), "utf-8")
    diff = f"git diff -- {kb}/doc/a.raw.md"

    result = _invoke(kb, "report")

    assert result.exit_code == 1
    lines = result.output.splitlines()
    assert lines[0] == "doc"
    assert lines[1:4] == [
        "§1 [ai-fix, from page image — check against the PDF] "
        f"by claude-code · changes: text · {diff}",
        f"§2 [edited outside kb l3 fix apply] {diff}",
        "§x1 [removed outside kb l3 fix apply]",
    ]
    assert "  [content] p.1" not in lines  # §1 already printed as an ai-fix
    assert "3 section(s) awaiting review." in result.output


def test_report_verified_ai_fix_line(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(
        kb,
        baseline={"2": digests["2"]},
        entries=[_fix_entry("1", digests["1"], changes=["re-id", "join"])],
    )

    result = _invoke(kb, "report")

    assert result.exit_code == 1
    assert (
        f"§1 [ai-fix] by cursor · changes: re-id, join · git diff -- {kb}/doc/a.raw.md"
        in result.output.splitlines()
    )


def test_confirm_ai_fix_unblocks(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(kb, baseline={"2": digests["2"]}, entries=[_fix_entry("1", digests["1"])])
    assert report.blocked_docs(kb) == [("doc", ["1"])]

    result = _invoke(kb, "confirm", "doc", "--section", "1", "--by", "Rev <r@x>")

    assert result.exit_code == 0
    assert "confirmed: §1" in result.output
    assert report.blocked_docs(kb) == []
    entry = fixrecord.load(kb / "doc").sections[0]
    assert entry.confirmed.by == "Rev <r@x>"
    assert entry.confirmed.l3_sha256 == digests["1"]


def test_confirm_edited_outside_records_human_entry(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(kb, baseline={"1": "stale", "2": digests["2"]})

    result = _invoke(kb, "confirm", "doc", "--section", "1", "--by", "Rev <r@x>")

    assert result.exit_code == 0
    assert report.blocked_docs(kb) == []
    entry = fixrecord.load(kb / "doc").sections[0]
    assert (entry.id, entry.file, entry.by, entry.changes) == ("1", "a", "human", [])
    assert entry.l3_sha256 == digests["1"]
    assert entry.confirmed.by == "Rev <r@x>"


def test_confirm_untracked_unit_takes_file_from_manifest(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(kb, baseline={"2": digests["2"]})
    assert report.blocked_docs(kb) == [("doc", ["1"])]

    _invoke(kb, "confirm", "doc", "--section", "1", "--by", "r")

    assert report.blocked_docs(kb) == []
    assert fixrecord.load(kb / "doc").sections[0].file == "a"


def test_confirm_removed_outside_drops_tracking(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(
        kb,
        baseline={"1": digests["1"], "2": digests["2"], "x1": "gone"},
        entries=[_fix_entry("x1", "gone")],
    )
    assert report.blocked_docs(kb) == [("doc", ["x1"])]

    result = _invoke(kb, "confirm", "doc", "--section", "x1", "--by", "r")

    assert result.exit_code == 0
    assert "confirmed: §x1" in result.output
    rec = fixrecord.load(kb / "doc")
    assert sorted(rec.baseline) == ["1", "2"]
    assert rec.sections == []
    assert report.blocked_docs(kb) == []


def test_confirm_all_covers_both_files(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _flag(kb, "1")
    _fix(kb, baseline={"1": digests["1"], "2": "stale"})

    declined = runner.invoke(
        app,
        ["l3", "confirm", "doc", "--all", "--by", "r", "--kb-dir", str(kb)],
        input="n\n",
    )
    accepted = _invoke(kb, "confirm", "doc", "--all", "--by", "r", "--yes")

    assert "Confirm all 2 flagged section(s) of doc?" in declined.output
    assert accepted.exit_code == 0
    assert "confirmed: §1, §2" in accepted.output
    assert report.load(kb / "doc").sections[0].confirmed is not None
    assert report.blocked_docs(kb) == []


def test_confirm_with_only_l3fix_file(tmp_path):
    kb = _git_kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    _fix(kb, baseline={"2": digests["2"]}, entries=[_fix_entry("1", digests["1"])])
    assert not (kb / "doc" / report.FILE_NAME).exists()

    unknown = _invoke(kb, "confirm", "doc", "--section", "9", "--by", "r")
    accepted = _invoke(kb, "confirm", "doc", "--all", "--by", "r", "--yes")

    assert unknown.exit_code == 1
    assert "no flagged section 9 (flagged: 1)" in unknown.output
    assert accepted.exit_code == 0
    assert report.blocked_docs(kb) == []
