"""Final whole-branch review fixes: apply cannot launder, summarize gate, links."""

from __future__ import annotations

import pytest

from strata_kb.cli import app
from strata_kb.l3check import fixrecord, report
from tests.test_l3fix_apply import (
    FIXED_42,
    IMAGE,
    NOTE,
    _apply,
    _build,
    _draft,
    _raw_path,
    _read,
    runner,
)

KB_BODY = "được nghỉ phép năm"
HAND = "không được nghỉ phép năm"


@pytest.fixture
def kb(tmp_path):
    return _build(tmp_path)


def test_apply_refuses_unit_edited_outside_apply(kb):
    raw = _raw_path(kb)
    raw.write_text(_read(raw).replace(KB_BODY, HAND), encoding="utf-8")
    assert fixrecord.blocked_ids(kb, "doc") == [("x1", fixrecord.EDITED)]
    _draft(kb, "x1", FIXED_42.replace(KB_BODY, HAND))

    [r] = _apply(kb)

    assert r.status == "rejected"
    assert r.reason == (
        "status: §x1 was edited outside kb l3 fix apply "
        "— run kb l3 confirm or restore it first"
    )
    assert fixrecord.blocked_ids(kb, "doc") == [("x1", fixrecord.EDITED)]


def test_unverified_flag_survives_a_chained_fix(kb):
    bad = FIXED_42.replace(KB_BODY, HAND)
    _draft(kb, "x1", bad)
    assert _apply(kb, pdf_pages={}, from_image={"x1"})[0].status == "applied"
    assert [e.verified for e in fixrecord.load(kb / "doc").sections] == [False]
    joined = bad.replace("theo hợp đồng.\n\nNghỉ phép", "theo hợp đồng. Nghỉ phép")
    _draft(kb, "4.2", joined)

    [r] = _apply(kb)

    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert [(e.id, e.verified) for e in rec.sections] == [("4.2", False)]


def test_confirmed_unverified_entry_does_not_taint_the_next_fix(kb):
    bad = FIXED_42.replace(KB_BODY, HAND)
    _draft(kb, "x1", bad)
    _apply(kb, pdf_pages={}, from_image={"x1"})
    rec = fixrecord.load(kb / "doc")
    fixrecord.confirm(
        kb / "doc", ["4.2"], "human", "t", report.current_digests(kb, "doc")
    )
    assert fixrecord.blocked_ids(kb, "doc") == []
    _draft(
        kb,
        "4.2",
        bad.replace("theo hợp đồng.\n\nNghỉ phép", "theo hợp đồng. Nghỉ phép"),
    )

    [r] = _apply(kb, pdf_pages={}, from_image={"4.2"})

    assert r.status == "applied", r.reason
    assert report.blocked_docs(kb) == [("doc", ["4.2"])]


def _applied(kb):
    _draft(kb, "x1", FIXED_42)
    assert _apply(kb)[0].status == "applied"


def test_print_prompt_refuses_a_doc_with_an_unconfirmed_ai_fix(kb):
    _applied(kb)

    res = runner.invoke(
        app, ["summarize", "doc", "--print-prompt", "--kb-dir", str(kb)]
    )

    assert res.exit_code == 1
    assert "[skip] doc: L3 review pending (1 section(s)) — kb l3 report doc" in (
        res.output
    )
    assert "===" not in res.output


def test_print_prompt_refuses_a_doc_with_an_outside_edit(kb):
    raw = _raw_path(kb)
    raw.write_text(_read(raw).replace(KB_BODY, HAND), encoding="utf-8")

    res = runner.invoke(
        app, ["summarize", "doc", "--print-prompt", "--kb-dir", str(kb)]
    )

    assert res.exit_code == 1
    assert "L3 review pending" in res.output


def test_status_counts_ai_fix_and_outside_edit_sections(kb):
    _applied(kb)

    res = runner.invoke(app, ["status", "--kb-dir", str(kb)])

    assert res.exit_code == 0
    assert "  L3 check: 1 section(s) awaiting review" in res.output


@pytest.mark.parametrize(
    "name",
    [
        "claude-skill-kb-ingest.md",
        "copilot-kb-ingest.prompt.md",
        "cursor-kb-ingest.md",
    ],
)
def test_ingest_templates_summarize_only_after_l3_confirm(name):
    from pathlib import Path

    import strata_kb

    text = (Path(strata_kb.__file__).parent / "templates/init" / name).read_text(
        encoding="utf-8"
    )

    assert "fill them only after the\n     user has run `kb l3 confirm`" in text
    assert "only\n   after the user has run `kb l3 confirm`" in text


IMG_B = "![Sơ đồ phê duyệt](assets/" + "b" * 64 + ".png)"


@pytest.mark.parametrize(
    ("mutate", "target"),
    [
        (lambda d: d.replace(IMAGE, IMG_B), "!assets/" + "b" * 64 + ".png"),
        (
            lambda d: d.replace(NOTE, "![](assets/" + "c" * 64 + ".png)\n\n" + NOTE),
            "!assets/" + "c" * 64 + ".png",
        ),
        (
            lambda d: d.replace(
                "theo hợp đồng.", "theo [hợp đồng](https://example.com/x)."
            ),
            "https://example.com/x",
        ),
        (lambda d: d.replace(IMAGE + "\n\n", ""), "!assets/" + "a" * 64 + ".png"),
        (
            lambda d: d.replace(NOTE, NOTE + "\n\n[1]: https://example.com/ref"),
            "https://example.com/ref",
        ),
    ],
    ids=["swap", "new-image", "new-link", "removed-image", "definition"],
)
def test_changed_image_or_link_target_is_rejected(kb, mutate, target):
    _draft(kb, "x1", mutate(FIXED_42))

    [r] = _apply(kb)

    assert r.status == "rejected"
    assert r.reason == f"links: {target}"


def test_unchanged_links_pass(kb):
    _draft(kb, "x1", FIXED_42)

    assert _apply(kb)[0].status == "applied"


def test_skill_body_says_report_exit_1_is_normal():
    from strata_kb.initcmd import read_template

    text = read_template("claude-skill-kb-l3-fix.md")

    assert "`kb l3 report` exits 1 whenever any section awaits review" in text


def test_readme_does_not_promise_changed_files():
    from pathlib import Path

    readme = (Path(__file__).resolve().parent.parent / "README.md").read_text(
        encoding="utf-8"
    )

    assert "the files it changed" not in readme
